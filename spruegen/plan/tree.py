"""Ruteo del árbol: une los puntos de attach (cara interna) con la tapa del stem.

Frame del job (mm, Z arriba): stem Ø10 x 35 en el origen, anillo coaxial encima, attach primario en -Y.

Topologías:
  single  un feeder directo (v0.1).
  spider  un feeder directo por attach, nudos repartidos sobre la tapa del stem.
  y       attaches cercanos de a pares comparten un tronco: stem -> bifurcación B -> dos brazos.
  auto    los attaches salen de `analysis` (cantidad y lugar); pares cercanos -> Y, resto directo.

Cada tramo pasa los mismos chequeos que v0.1: piel externa >= 0.3 mm (rayos contra la cara externa real),
sin rozar el anillo fuera del join, penetración acotada por el recorte cilíndrico.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import trimesh

from spruegen.construct import sprues as build
from spruegen.detect.features import OuterGrid, angdist, plane_basis, unit
from spruegen.plan.policy import CLEARANCE_MM, PEN_RANGE, SKIN_MARGIN_MM, feeder_diameter, solve_feeder
from spruegen.schemas import Branch, Candidate, Features, Feeder, Hub, PolicyError, Profile, Sphere, Stem

Z_SEARCH_MM = 8.0
Z_STEP_MM = 0.25


class RouteError(PolicyError):
    def __init__(self, msg: str, index: int | None = None):
        super().__init__(msg)
        self.index = index


@dataclass
class Route:
    T: np.ndarray
    stem: Stem
    feeders: list[Feeder]
    attaches: list[Candidate]
    branches: list[Branch]
    fillets: list[Sphere]
    hub: Hub | None
    groups: list[list[int]]
    mode: str
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- frame


def rotation_for(feats: Features, primary: Candidate) -> tuple[np.ndarray, np.ndarray]:
    """Rotación input->job: eje del dedo -> +Z, attach primario -> -Y."""
    axis = unit(feats.axis)
    c = np.array(feats.center)
    u, v = plane_basis(axis)
    th = math.radians(primary.theta_deg)
    e1 = math.cos(th) * u + math.sin(th) * v
    y_new = -e1
    x_new = np.cross(y_new, axis)
    return np.vstack([x_new, y_new, axis]), c


def make_T(Rm: np.ndarray, c: np.ndarray, z_center: float) -> np.ndarray:
    T = np.eye(4)
    T[:3, :3] = Rm
    T[:3, 3] = -Rm @ c + np.array([0.0, 0.0, z_center])
    return T


def penetration(t: float, p: Profile) -> float:
    pen = float(np.clip(p.boolean_overlap_mm + 0.2, *PEN_RANGE))
    pen = min(pen, t - SKIN_MARGIN_MM)
    if pen < PEN_RANGE[0]:
        raise RouteError(f"espesor {t:.2f} mm no deja penetrar {PEN_RANGE[0]} mm con {SKIN_MARGIN_MM} mm de piel")
    return pen


# ---------------------------------------------------------------- geometría de tramos


def solve_direct_fixed(r_in: float, V: float, R: float, p: Profile, L_target: float | None):
    """Feeder directo con caída vertical fija V: elige rho (nudo sobre la tapa) -> (rho, alpha, L)."""
    if V <= 0:
        return None
    rho_max = max(0.0, p.stem_d_mm / 2 - R)
    a_lo, a_hi = (math.radians(a) for a in p.feeder_angle_deg)
    L_lo, L_hi = p.feeder_len_mm
    target = L_target if L_target is not None else p.feeder_len_default_mm
    best = None
    for rho in np.linspace(0.0, rho_max, 41):
        H = r_in - rho
        if H <= 0:
            continue
        a = math.atan2(H, V)
        L = math.hypot(H, V)
        if not (a_lo - 1e-9 <= a <= a_hi + 1e-9 and L_lo - 1e-9 <= L <= L_hi + 1e-9):
            continue
        cost = abs(L - target)
        if best is None or cost < best[0]:
            best = (cost, float(rho), float(a), float(L))
    return None if best is None else best[1:]


def make_feeder(A, N, R, pen, r_in, p: Profile, node_kind="stem") -> Feeder:
    A = np.asarray(A, float)
    N = np.asarray(N, float)
    d_in = unit(N - A)  # de la cara interna hacia el nudo
    L = float(np.linalg.norm(N - A))
    alpha = math.acos(float(np.clip(-d_in[2], -1, 1)))  # ángulo desde la vertical
    rhat = unit(np.array([A[0], A[1], 0.0]))
    sin_r = max(float(-(d_in @ rhat)), 0.15)  # qué tan "radial" entra a la pared
    ov = p.boolean_overlap_mm
    start = N + d_in * (ov / max(math.cos(alpha), 0.3)) if node_kind == "stem" else N.copy()
    # se extiende más allá de la pared para que toda la sección toque; el recorte fija la penetración
    end = A - d_in * ((pen + R * math.sqrt(max(0.0, 1 - sin_r**2))) / sin_r + 0.2)
    Rs = R + p.join_fillet_r_mm
    s = min(0.5 * Rs / sin_r, L / 3)
    return Feeder(
        d_mm=2 * R,
        len_mm=L,
        angle_deg=math.degrees(alpha),
        node=N.tolist(),
        attach=A.tolist(),
        start=start.tolist(),
        end=end.tolist(),
        penetration_mm=pen,
        outward_depth_mm=pen,
        stem_overlap_mm=ov,
        clip_r_mm=r_in + pen,
        ring_fillet=Sphere(center=(A + d_in * s).tolist(), r_mm=Rs, role="ring_join"),
        node_kind=node_kind,
    )


def _y_geometry(As, hs, rs, zc, p: Profile):
    """Punto de bifurcación B y chequeo de brazos para un par de attaches. None si no cabe."""
    tc = p.tree
    phis = [math.atan2(a[1], a[0]) for a in As]
    phiB = math.atan2(sum(math.sin(x) for x in phis), sum(math.cos(x) for x in phis))
    rhoB = tc.y_branch_radius_frac * float(np.mean(rs))
    Bxy = rhoB * np.array([math.cos(phiB), math.sin(phiB)])
    Hs = [float(np.linalg.norm(np.asarray(a[:2]) - Bxy)) for a in As]
    tan_a = math.tan(math.radians(tc.arm_angle_deg))
    zB = zc + float(np.mean([h - H / tan_a for h, H in zip(hs, Hs)]))
    for h, H in zip(hs, Hs):
        V = zc + h - zB
        if V <= 0:
            return None
        a = math.degrees(math.atan2(H, V))
        L = math.hypot(H, V)
        if abs(a - tc.arm_angle_deg) > 15.0 or not (tc.arm_len_mm[0] <= L <= tc.arm_len_mm[1]):
            return None
    if zB - p.stem_h_mm < tc.trunk_min_len_mm - 1e-9:
        return None
    return phiB, rhoB, zB


def _y_zc_min(As, hs, rs, p: Profile) -> float:
    """z_center mínimo para que el tronco de la Y mida >= trunk_min_len."""
    tc = p.tree
    phis = [math.atan2(a[1], a[0]) for a in As]
    phiB = math.atan2(sum(math.sin(x) for x in phis), sum(math.cos(x) for x in phis))
    rhoB = tc.y_branch_radius_frac * float(np.mean(rs))
    Bxy = rhoB * np.array([math.cos(phiB), math.sin(phiB)])
    tan_a = math.tan(math.radians(tc.arm_angle_deg))
    Hs = [float(np.linalg.norm(np.asarray(a[:2]) - Bxy)) for a in As]
    return p.stem_h_mm + tc.trunk_min_len_mm - float(np.mean([h - H / tan_a for h, H in zip(hs, Hs)]))


# ---------------------------------------------------------------- chequeos


def check_placement(ring_job: trimesh.Trimesh, p: Profile, warnings: list[str], extra_top: float = 0.0) -> None:
    zmin, zmax = ring_job.bounds[:, 2]
    if zmin < p.stem_h_mm - 1e-6 and np.hypot(*ring_job.bounds[:, :2].T).min() < p.stem_d_mm / 2:
        raise RouteError("el anillo quedaría dentro del stem; revisa la geometría")
    piece_h = max(zmax, extra_top) - p.stem_h_mm
    if piece_h > p.ring_space_mm:
        raise RouteError(
            f"la pieza (anillo + árbol) mide {piece_h:.1f} mm sobre el stem > ring_space_mm {p.ring_space_mm} mm"
        )
    lateral = float(np.max(ring_job.extents[:2]))
    if lateral > p.button_d_mm:
        warnings.append(f"el anillo mide {lateral:.1f} mm de ancho > button_d_mm {p.button_d_mm} mm")


def check_feeder(ring_job, grid: OuterGrid | None, T, f: Feeder, p: Profile, idx: int) -> None:
    if grid is not None and "outer_surface" in p.keepout:
        near = build.build_ring_join(f)
        near.apply_transform(np.linalg.inv(T))
        clr = grid.min_clearance(near)
        if clr < SKIN_MARGIN_MM:
            raise RouteError(
                f"el feeder queda a {clr:.2f} mm de la cara externa (mín. {SKIN_MARGIN_MM} mm): "
                "el shank es delgado alrededor del attach",
                idx,
            )
    A = np.array(f.attach)
    N = np.array(f.node)
    d_in = unit(N - A)
    R = f.d_mm / 2
    s = float(np.linalg.norm(np.array(f.ring_fillet.center) - A)) if f.ring_fillet else 0.0
    Rs = f.ring_fillet.r_mm if f.ring_fillet else R
    far = s + Rs + 0.5
    if f.len_mm > far:
        pts = A[None] + np.linspace(far, f.len_mm, 12)[:, None] * d_in[None]
        with np.errstate(divide="ignore", invalid="ignore"):  # astillas de área cero
            sd = trimesh.proximity.signed_distance(ring_job, pts)  # >0 dentro
        if np.any(sd > -(R + CLEARANCE_MM)):
            raise RouteError(
                "el feeder roza el anillo fuera del punto de attach (¿anillo muy angosto o con cabeza "
                "colgando hacia el stem?)",
                idx,
            )


def check_segment_free(ring_job, a, b, R, idx: int) -> None:
    a, b = np.asarray(a, float), np.asarray(b, float)
    pts = a[None] + np.linspace(0, 1, 10)[:, None] * (b - a)[None]
    with np.errstate(divide="ignore", invalid="ignore"):
        sd = trimesh.proximity.signed_distance(ring_job, pts)
    if np.any(sd > -(R + CLEARANCE_MM)):
        raise RouteError("el tronco de la Y choca con el anillo", idx)


# ---------------------------------------------------------------- ruteo


def route(
    ring_in: trimesh.Trimesh,
    feats: Features,
    attaches: list[Candidate],
    groups: list[list[int]],
    p: Profile,
    grid: OuterGrid | None,
    mode: str,
) -> Route:
    """Geometría completa para un conjunto de attaches ya elegido. RouteError(index) si un attach no sirve."""
    warnings: list[str] = []
    if p.attach_mode != "inner_shank":
        raise PolicyError(f"attach_mode {p.attach_mode!r} no soportado (v1: inner_shank)")
    for i, a in enumerate(attaches):
        if a.thickness_mm < p.min_attach_thickness_mm - 1e-9:
            raise RouteError(f"attach con espesor {a.thickness_mm:.2f} mm < mínimo {p.min_attach_thickness_mm} mm", i)
    Rm, c = rotation_for(feats, attaches[0])
    rel = [Rm @ (np.array(a.point) - c) for a in attaches]  # (x, y, h) en el frame del job
    hs = [float(r[2]) for r in rel]
    rs = [a.r_inner_mm for a in attaches]
    pens = [penetration(a.thickness_mm, p) for a in attaches]
    t_min = min(a.thickness_mm for a in attaches)
    if t_min < p.min_attach_thickness_mm + 0.2:
        warnings.append(f"espesor en el attach ({t_min:.2f} mm) justo en el mínimo ({p.min_attach_thickness_mm} mm)")
    Rf = [feeder_diameter(t_min if p.tree.uniform else a.thickness_mm, p) / 2 for a in attaches]
    stem_r = p.stem_d_mm / 2

    # altura del anillo (z del centro): la fija el primario directo (v0.1) o la necesidad de las Y
    prim_group = next(g for g in groups if 0 in g)
    zc_req = []
    sol0 = None
    if len(prim_group) == 1:
        sol0 = solve_feeder(rs[0], Rf[0], p)
        if sol0 is None:
            raise RouteError(
                f"no hay feeder que cumpla largo {p.feeder_len_mm} mm y ángulo {p.feeder_angle_deg}° desde la "
                f"cara interna (r={rs[0]:.2f} mm) hasta la tapa del stem Ø{p.stem_d_mm}.",
                0,
            )
        _, rho0, a0, L0 = sol0
        zc_req.append(p.stem_h_mm + L0 * math.cos(a0) - hs[0])
    L_target = sol0[3] if sol0 else None
    for g in groups:
        if len(g) == 2:
            zc_req.append(_y_zc_min([rel[i] for i in g], [hs[i] for i in g], [rs[i] for i in g], p))
    zc0 = max(zc_req)

    plan_geo = None
    for zc in zc0 + np.arange(0.0, Z_SEARCH_MM + 1e-9, Z_STEP_MM):
        geo: dict[int, tuple] = {}
        ok = True
        bad = None
        for g in groups:
            if len(g) == 1:
                i = g[0]
                if i == 0 and sol0 is not None and abs(zc - zc0) < 1e-9 and zc0 == zc_req[0]:
                    geo[i] = ("direct", sol0[1], sol0[2], sol0[3])
                    continue
                sol = solve_direct_fixed(rs[i], zc + hs[i] - p.stem_h_mm, Rf[i], p, L_target)
                if sol is None:
                    ok, bad = False, i
                    break
                geo[i] = ("direct",) + sol
            else:
                yg = _y_geometry([rel[i] for i in g], [hs[i] for i in g], [rs[i] for i in g], zc, p)
                if yg is None:
                    ok, bad = False, g[0]
                    break
                geo[tuple(g)] = ("y",) + yg
        if ok:
            plan_geo = (zc, geo)
            break
    if plan_geo is None:
        raise RouteError(
            f"no hay altura del anillo en la que todos los feeders cumplan largo {p.feeder_len_mm} mm y "
            f"ángulo {p.feeder_angle_deg}° (attach #{(bad or 0) + 1})",
            bad,
        )
    zc, geo = plan_geo
    T = make_T(Rm, c, zc)

    feeders: list[Feeder | None] = [None] * len(attaches)
    branches: list[Branch] = []
    fillets: list[Sphere] = []
    f_r = p.join_fillet_r_mm
    for g in groups:
        if len(g) == 1:
            i = g[0]
            _, rho, alpha, L = geo[i]
            A = np.array([rel[i][0], rel[i][1], zc + hs[i]])
            phi = math.atan2(A[1], A[0])
            N = np.array([rho * math.cos(phi), rho * math.sin(phi), p.stem_h_mm])
            feeders[i] = make_feeder(A, N, Rf[i], pens[i], rs[i], p, "stem")
            fillets.append(Sphere(center=N.tolist(), r_mm=Rf[i] + f_r, role="stem_join"))
        else:
            _, phiB, rhoB, zB = geo[tuple(g)]
            B = np.array([rhoB * math.cos(phiB), rhoB * math.sin(phiB), zB])
            d_arm = [2 * Rf[i] for i in g]
            d_t = math.sqrt(sum(d * d for d in d_arm))
            clipped = d_t > p.tree.trunk_d_max_mm
            if clipped:
                d_t = p.tree.trunk_d_max_mm
                warnings.append(f"tronco de la Y limitado a Ø{d_t} mm (< área de los brazos)")
            rhoN = min(rhoB, max(0.0, stem_r - d_t / 2))
            N = np.array([rhoN * math.cos(phiB), rhoN * math.sin(phiB), p.stem_h_mm])
            d_tr = unit(N - B)
            cos_t = max(-d_tr[2], 0.3)
            start = N + d_tr * (p.boolean_overlap_mm / cos_t)
            branches.append(Branch(start=start.tolist(), end=B.tolist(), d_mm=d_t, arms=list(g), area_clipped=clipped))
            fillets.append(Sphere(center=N.tolist(), r_mm=d_t / 2 + f_r, role="stem_join"))
            fillets.append(Sphere(center=B.tolist(), r_mm=d_t / 2 + 0.5 * f_r, role="branch_node"))
            for i in g:
                A = np.array([rel[i][0], rel[i][1], zc + hs[i]])
                feeders[i] = make_feeder(A, B, Rf[i], pens[i], rs[i], p, "branch")

    hub = None
    if p.tree.hub == "cone":
        hub = Hub(z0=p.stem_h_mm - p.boolean_overlap_mm, z1=p.stem_h_mm + 1.5, r0=stem_r, r1=0.62 * stem_r)

    stem = Stem(d_mm=p.stem_d_mm, h_mm=p.stem_h_mm, origin=[0.0, 0.0, 0.0], axis=[0.0, 0.0, 1.0])
    ring_job = ring_in.copy()
    ring_job.apply_transform(T)
    check_placement(ring_job, p, warnings)
    for i, f in enumerate(feeders):
        if f.len_mm > 12.0:
            warnings.append(f"feeder #{i + 1} de {f.len_mm:.1f} mm (> 12 mm)")
        if f.d_mm > feats.band_width_mm:
            warnings.append(
                f"feeder Ø{f.d_mm:.2f} mm más ancho que la banda ({feats.band_width_mm:.2f} mm): "
                "el filete asomará por los cantos interiores"
            )
        try:
            check_feeder(ring_job, grid, T, f, p, i)
        except RouteError as e:
            # sobre ventanas del lattice solo queda la cáscara interna: probar la penetración mínima
            if f.penetration_mm <= PEN_RANGE[0] + 1e-9 or "cara externa" not in str(e):
                raise
            A, N = np.array(f.attach), np.array(f.node)
            f2 = make_feeder(A, N, f.d_mm / 2, PEN_RANGE[0], f.clip_r_mm - f.penetration_mm, p, f.node_kind)
            check_feeder(ring_job, grid, T, f2, p, i)
            feeders[i] = f2
            warnings.append(f"feeder #{i + 1}: penetración reducida a {PEN_RANGE[0]} mm (cáscara delgada)")
    for b in branches:
        check_segment_free(ring_job, b.start, b.end, b.d_mm / 2, b.arms[0])
    return Route(
        T=T,
        stem=stem,
        feeders=feeders,
        attaches=list(attaches),
        branches=branches,
        fillets=fillets,
        hub=hub,
        groups=groups,
        mode=mode,
        warnings=sorted(set(warnings), key=warnings.index),
    )


# ---------------------------------------------------------------- selección de attaches


def alternates_for(target_theta_deg: float, pool: list[Candidate], tol_deg: float, exclude=()) -> list[Candidate]:
    """Candidatos dentro de ±tol del ángulo objetivo, más gruesos primero, luego más cercanos."""
    t = math.radians(target_theta_deg)
    out = []
    for c in pool:
        d = float(angdist(math.radians(c.theta_deg), t))
        if d <= math.radians(tol_deg) + 1e-9 and c not in exclude:
            out.append((round(-c.thickness_mm / 0.15), d, c))
    out.sort(key=lambda x: (x[0], x[1]))
    return [c for *_, c in out]


def pair_groups(attaches: list[Candidate], merge_deg: float, force: bool = False) -> list[list[int]]:
    """Agrupa attaches de a pares por cercanía angular (<= merge_deg, o todos si force)."""
    n = len(attaches)
    th = [math.radians(a.theta_deg) for a in attaches]
    pairs = sorted(
        ((float(angdist(th[i], th[j])), i, j) for i in range(n) for j in range(i + 1, n)),
        key=lambda x: x[0],
    )
    used: set[int] = set()
    groups: list[list[int]] = []
    for d, i, j in pairs:
        if i in used or j in used:
            continue
        if force or d <= math.radians(merge_deg) + 1e-9:
            groups.append([i, j])
            used |= {i, j}
    groups += [[i] for i in range(n) if i not in used]
    return groups


def plan_with_alternates(
    ring_in,
    feats: Features,
    attaches: list[Candidate],
    alternates: list[list[Candidate]],
    groups_fn,
    p: Profile,
    grid: OuterGrid | None,
    mode: str,
    max_attempts: int = 60,
    min_sep_deg: float = 30.0,
) -> Route:
    """Intenta rutear; si un attach falla lo reemplaza por su siguiente alternativa (o lo descarta)."""
    cur = list(attaches)
    alts = [[c for c in a if c not in attaches] for a in alternates]
    dropped: list[str] = []
    reasons: list[str] = []
    for _ in range(max_attempts):
        try:
            r = route(ring_in, feats, cur, groups_fn(cur), p, grid, mode)
            r.warnings += dropped
            return r
        except RouteError as e:
            reasons.append(str(e))
            i = e.index if e.index is not None else 0
            others = [c for k, c in enumerate(cur) if k != i]

            def clashes(c):
                return any(
                    float(angdist(math.radians(c.theta_deg), math.radians(o.theta_deg))) < math.radians(min_sep_deg)
                    for o in others
                )

            while alts[i] and clashes(alts[i][0]):
                alts[i].pop(0)
            if alts[i]:
                cur[i] = alts[i].pop(0)
                continue
            if len(cur) == 1:
                break
            dropped.append(
                f"se descartó el attach cerca de theta={cur[i].theta_deg:.0f}° ({e}); quedan {len(cur) - 1} feeders"
            )
            del cur[i]
            del alts[i]
    uniq = sorted(set(reasons), key=reasons.index)[:3]
    raise PolicyError("no se pudo rutear el árbol. Motivos: " + " | ".join(uniq))


def plan_single(ring_in, feats, cands: list[Candidate], p, grid) -> tuple[int, Route]:
    """v0.1: prueba candidatos en orden de ranking; el primero que pasa todos los chequeos."""
    reasons = []
    for rank, cand in enumerate(cands):
        try:
            return rank, route(ring_in, feats, [cand], [[0]], p, grid, "single")
        except RouteError as e:
            reasons.append(str(e))
    uniq = sorted(set(reasons), key=reasons.index)[:3]
    raise PolicyError(
        f"ninguno de los {len(cands)} candidatos internos admite un feeder seguro. Motivos: " + " | ".join(uniq)
    )


def spread_targets(theta0: float, n: int, mode: str, span_deg: float) -> list[float]:
    """Ángulos objetivo: spider = repartidos 360/n; y = pares (±span/2) repartidos 360/pares."""
    if mode == "spider" or n == 1:
        return [theta0 + k * 360.0 / n for k in range(n)]
    n_pairs = math.ceil(n / 2)
    out = []
    for j in range(n_pairs):
        center = theta0 + span_deg / 2 + j * 360.0 / n_pairs
        out.append(center - span_deg / 2)
        if len(out) < n:
            out.append(center + span_deg / 2)
    return out


def plan_spread(ring_in, feats, pool: list[Candidate], n: int, mode: str, p: Profile, grid) -> Route:
    """spider / y con cantidad fija: primario = mejor candidato; el resto lo más cerca posible del reparto
    simétrico (la ventana angular se abre de a 20° hasta 60° si el shank no tiene parches gruesos ahí)."""
    tol = p.tree.angle_tolerance_deg
    span = min(p.tree.y_merge_deg * 0.8, 360.0 / max(n, 1))
    min_sep = math.radians(45.0 if mode == "spider" else 30.0)
    best_partial = None
    since_partial = 0
    for primary in pool[:12]:
        if best_partial is not None:
            since_partial += 1
            if since_partial > 3:  # ya hay una solución parcial y no mejora
                break
        targets = spread_targets(primary.theta_deg, n, mode, span)
        chosen = [primary]
        alternates = [[c for c in alternates_for(primary.theta_deg, pool, tol, exclude=[primary])]]
        for t in targets[1:]:
            # alternativas por anillos de tolerancia: primero ±tol, luego ±tol+20... hasta cualquier ángulo
            alts, tol_k = [], tol
            while tol_k <= 180.0 + 1e-9:
                alts += [
                    c for c in alternates_for(t, pool, tol_k, exclude=chosen)
                    if c not in alts
                    and all(float(angdist(math.radians(c.theta_deg), math.radians(x.theta_deg))) >= min_sep
                            for x in chosen)
                ]
                tol_k += 20.0
            if alts:
                chosen.append(alts[0])
                alternates.append(alts[1:])
        groups_fn = (lambda cur: [[i] for i in range(len(cur))]) if mode == "spider" else (
            lambda cur: pair_groups(cur, 180.0, force=True)
        )
        try:
            r = plan_with_alternates(
                ring_in, feats, chosen, alternates, groups_fn, p, grid, mode, min_sep_deg=math.degrees(min_sep)
            )
        except PolicyError:
            continue
        if len(r.feeders) == n:
            ths = sorted(a.theta_deg % 360.0 for a in r.attaches)
            gaps = [((ths[(k + 1) % n] - ths[k]) % 360.0) for k in range(n)]
            if mode == "spider" and n > 1 and max(gaps) - min(gaps) > 2 * tol:
                r.warnings.append(
                    f"spider asimétrico: el shank solo admite attach seguro en algunas zonas "
                    f"(huecos {', '.join(f'{g:.0f}°' for g in gaps)})"
                )
            return r
        if best_partial is None or len(r.feeders) > len(best_partial.feeders):
            best_partial, since_partial = r, 0
    if best_partial is not None:
        best_partial.warnings.append(
            f"{mode}: solo {len(best_partial.feeders)} de {n} feeders caben con attach interno seguro en este anillo"
        )
        return best_partial
    raise PolicyError(f"no se encontraron attaches internos para modo {mode}")
