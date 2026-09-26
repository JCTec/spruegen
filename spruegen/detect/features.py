"""Detección de features: eje del dedo, cara interna vs externa, espesor local, candidatos de attach.

Todo se mide en el frame del STL de entrada. Coordenadas cilíndricas alrededor del eje del dedo:
  theta: ángulo en el plano del anillo (base u, v perpendicular al eje)
  h:     posición axial relativa al centro del aro (0 = media altura de la banda)
  r:     distancia al eje
"""

from __future__ import annotations

import math

import numpy as np
import trimesh

from spruegen.schemas import Candidate, FeatureError, Features, Profile

DEDUP_TOL = 1e-3
N_THETA = 180
H_STEP = 0.25
H_EDGE = 0.15
THICK_TOL = 0.15
TUNNEL_MIN_OPEN = 0.9


# ---------------------------------------------------------------- geometría básica


def unit(v) -> np.ndarray:
    v = np.asarray(v, dtype=float)
    n = np.linalg.norm(v)
    if n == 0:
        raise FeatureError("vector nulo")
    return v / n


def plane_basis(axis: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Base ortonormal (u, v) del plano perpendicular a `axis` (determinista)."""
    ref = np.array([1.0, 0.0, 0.0]) if abs(axis[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    u = unit(np.cross(axis, ref))
    v = np.cross(axis, u)
    return u, v


def canonical_axis(axis: np.ndarray) -> np.ndarray:
    """Signo determinista: la componente de mayor magnitud queda positiva."""
    axis = unit(axis)
    return axis if axis[np.argmax(np.abs(axis))] > 0 else -axis


def ray_hits(mesh: trimesh.Trimesh, origins: np.ndarray, dirs: np.ndarray) -> list[list[float]]:
    """Distancias ordenadas (deduplicadas) de todas las intersecciones de cada rayo."""
    origins = np.asarray(origins, dtype=float)
    dirs = np.asarray(dirs, dtype=float)
    out: list[list[float]] = [[] for _ in range(len(origins))]
    if len(origins) == 0:
        return out
    loc, ri, _ = mesh.ray.intersects_location(origins, dirs, multiple_hits=True)
    if len(ri) == 0:
        return out
    dist = np.einsum("ij,ij->i", loc - origins[ri], dirs[ri])
    order = np.lexsort((dist, ri))
    for i in order:
        d = float(dist[i])
        if d <= 1e-6:
            continue
        lst = out[ri[i]]
        if not lst or d - lst[-1] > DEDUP_TOL:
            lst.append(d)
    return out


def fit_circle(xy: np.ndarray) -> tuple[np.ndarray, float]:
    """Círculo best-fit (Kasa, mínimos cuadrados)."""
    A = np.c_[xy, np.ones(len(xy))]
    b = (xy**2).sum(1)
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    c = sol[:2] / 2
    r = math.sqrt(max(sol[2] + (c**2).sum(), 0.0))
    return c, r


# ---------------------------------------------------------------- eje + centro


def _pca_axes(mesh: trimesh.Trimesh) -> list[np.ndarray]:
    """Ejes principales ordenados de menor a mayor varianza (ponderado por área)."""
    w = mesh.area_faces
    p = mesh.triangles_center
    mu = (p * w[:, None]).sum(0) / w.sum()
    q = p - mu
    cov = (q * w[:, None]).T @ q / w.sum()
    vals, vecs = np.linalg.eigh(cov)
    return [canonical_axis(vecs[:, i]) for i in np.argsort(vals)]


def _fit_center(mesh, axis, c0, n=72):
    """Itera: rayos radiales desde el eje -> primeros hits -> círculo best-fit."""
    u, v = plane_basis(axis)
    c = np.asarray(c0, dtype=float)
    th = np.linspace(0, 2 * np.pi, n, endpoint=False)
    dirs = np.outer(np.cos(th), u) + np.outer(np.sin(th), v)
    r = None
    for _ in range(4):
        hits = ray_hits(mesh, np.tile(c, (n, 1)), dirs)
        firsts = [(i, h[0]) for i, h in enumerate(hits) if h]
        if len(firsts) < 0.5 * n:
            return None, None
        pts = np.array([c + dirs[i] * d for i, d in firsts])
        xy = np.c_[(pts - c) @ u, (pts - c) @ v]
        dc, r = fit_circle(xy)
        c = c + dc[0] * u + dc[1] * v
        if np.linalg.norm(dc) < 1e-4:
            break
    return c, r


def _axial_span(mesh, axis, c):
    h = (mesh.vertices - c) @ axis
    return float(h.min()), float(h.max())


def _tunnel_open_frac(mesh, axis, c, r_in, hmin, hmax) -> float:
    """Fracción de rayos a lo largo del eje (dentro de 0.5*r_in) que no tocan metal."""
    u, v = plane_basis(axis)
    pts = [np.zeros(2)]
    for rr in np.linspace(0.1, 0.5, 5) * r_in:
        for t in np.linspace(0, 2 * np.pi, 12, endpoint=False):
            pts.append(np.array([rr * math.cos(t), rr * math.sin(t)]))
    pts = np.array(pts)
    origins = c + np.outer(pts[:, 0], u) + np.outer(pts[:, 1], v) + (hmin - 5.0) * axis
    hits = ray_hits(mesh, origins, np.tile(axis, (len(origins), 1)))
    span = (hmax - hmin) + 10.0
    blocked = sum(1 for h in hits if any(d < span for d in h))
    return 1.0 - blocked / len(origins)


def find_axis(mesh: trimesh.Trimesh, hint=None) -> dict:
    """Eje del dedo + centro del hueco. Prueba el hint o los 3 ejes PCA; exige túnel abierto."""
    cands = [(canonical_axis(hint), "hint")] if hint is not None else [
        (a, f"pca{i}") for i, a in enumerate(_pca_axes(mesh))
    ]
    c0 = mesh.bounds.mean(0)
    best = None
    for axis, src in cands:
        hmin, hmax = _axial_span(mesh, axis, c0)
        c_mid = c0 + axis * (hmin + hmax) / 2
        c, r = _fit_center(mesh, axis, c_mid)
        if c is None or r is None or r <= 0:
            continue
        hmin, hmax = _axial_span(mesh, axis, c)
        c = c + axis * (hmin + hmax) / 2
        hmin, hmax = _axial_span(mesh, axis, c)
        open_frac = _tunnel_open_frac(mesh, axis, c, r, hmin, hmax)
        res = dict(axis=axis, source=src, center=c, r_fit=r, hmin=hmin, hmax=hmax, open_frac=open_frac)
        if best is None or open_frac > best["open_frac"]:
            best = res
        if open_frac >= TUNNEL_MIN_OPEN:
            return res
    if best is None or best["open_frac"] < TUNNEL_MIN_OPEN:
        frac = 0.0 if best is None else best["open_frac"]
        raise FeatureError(
            f"no se detecta el hueco del dedo (túnel abierto {frac:.0%}). "
            "¿Es un anillo? Pasa finger_axis_hint en job.json."
        )
    return best


# ---------------------------------------------------------------- escaneo radial


def radial_scan(mesh, axis, c, hs, thetas):
    """Rayos desde el eje hacia afuera. Devuelve r1 (cara interna), r2 (externa), ok (hits limpios)."""
    u, v = plane_basis(axis)
    H, T = np.meshgrid(hs, thetas, indexing="ij")
    dirs = np.outer(np.cos(T).ravel(), u) + np.outer(np.sin(T).ravel(), v)
    origins = c + np.outer(H.ravel(), axis)
    hits = ray_hits(mesh, origins, dirs)
    r1 = np.full(len(hits), np.nan)
    r2 = np.full(len(hits), np.nan)
    ok = np.zeros(len(hits), bool)
    for i, h in enumerate(hits):
        if len(h) >= 2:
            r1[i], r2[i] = h[0], h[1]
            # número par de cruces = rayo limpio (no rozó una arista)
            ok[i] = len(h) % 2 == 0
    shape = H.shape
    return r1.reshape(shape), r2.reshape(shape), ok.reshape(shape)


def _erode(mask: np.ndarray, k_h: int, k_t: int) -> np.ndarray:
    """Erosión: una celda sobrevive si toda su ventana (±k_h filas, ±k_t cols, theta circular) es válida."""
    nh, nt = mask.shape
    out = mask.copy()
    for dh in range(-k_h, k_h + 1):
        for dt in range(-k_t, k_t + 1):
            shifted = np.roll(mask, dt, axis=1)
            if dh > 0:
                shifted = np.vstack([shifted[dh:], np.zeros((dh, nt), bool)])
            elif dh < 0:
                shifted = np.vstack([np.zeros((-dh, nt), bool), shifted[:dh]])
            out &= shifted
    return out


def angdist(a, b):
    d = np.abs((np.asarray(a) - b + np.pi) % (2 * np.pi) - np.pi)
    return d


HEAD_PROTRUSION_MM = 2.5


def _protrusion_head(mesh, axis, c, u, v, thetas):
    """Cabeza por silueta: sector donde la pieza sobresale >= 2.5 mm del radio exterior típico
    (detecta garras/canastas que los rayos atraviesan sin tocar)."""
    q = mesh.vertices - c
    r = np.linalg.norm(q - np.outer(q @ axis, axis), axis=1)
    th = np.arctan2(q @ v, q @ u) % (2 * np.pi)
    nb = len(thetas)
    b = np.minimum((th / (2 * np.pi) * nb).astype(int), nb - 1)
    rmax = np.full(nb, np.nan)
    np.fmax.at(rmax, b, r)
    if np.all(np.isnan(rmax)):
        return None
    med = np.nanmedian(rmax)
    exc = np.nan_to_num(rmax - med)
    head = exc >= HEAD_PROTRUSION_MM
    if not head.any():
        return None
    w = exc * head
    return float(math.atan2((w * np.sin(thetas)).sum(), (w * np.cos(thetas)).sum()))


def _detect_head(thetas, thick, r2):
    """Cabeza/setting: sector con espesor muy por encima de la mediana del shank."""
    t_theta = np.nanmax(np.where(np.isnan(thick), -np.inf, thick), axis=0)
    t_theta[~np.isfinite(t_theta)] = np.nan
    if np.all(np.isnan(t_theta)):
        return None
    med = np.nanmedian(t_theta)
    # un tallado exterior grueso no es cabeza: exige sobresalir ≥ 3 mm sobre el shank típico
    head = t_theta > max(2.0 * med, med + 3.0)
    if not head.any():
        return None
    w = np.nan_to_num(t_theta - med) * head
    return float(math.atan2((w * np.sin(thetas)).sum(), (w * np.cos(thetas)).sum()))


def detect(
    mesh: trimesh.Trimesh, profile: Profile, axis_hint=None, max_candidates: int = 10, respect_head: bool = True
) -> Features:
    warnings: list[str] = []
    ax = find_axis(mesh, axis_hint)
    axis, c = ax["axis"], ax["center"]
    u, v = plane_basis(axis)
    hmin, hmax = ax["hmin"], ax["hmax"]
    width = hmax - hmin

    lo, hi = hmin + H_EDGE, hmax - H_EDGE
    n_h = max(1, int(math.floor((hi - lo) / H_STEP)) + 1) if hi > lo else 1
    hs = np.linspace(lo, hi, n_h) if n_h > 1 else np.array([(hmin + hmax) / 2])
    thetas = np.linspace(0, 2 * np.pi, N_THETA, endpoint=False)
    r1, r2, ok = radial_scan(mesh, axis, c, hs, thetas)
    thick = r2 - r1

    t_min = profile.min_attach_thickness_mm
    valid = ok & (thick >= t_min)
    # footprint del feeder mínimo: el attach necesita un parche sólido alrededor, no un puente aislado
    r_med = float(np.nanmedian(r1[ok])) if ok.any() else ax["r_fit"]
    dth = 2 * np.pi / N_THETA
    k_t = max(1, int(math.ceil((profile.feeder_d_min_mm / 2) / r_med / dth)))
    k_h = 1 if n_h >= 3 else 0
    eroded = _erode(valid, k_h, k_t) if "lattice_thin" in profile.keepout else valid

    head_theta = _detect_head(thetas, np.where(ok, thick, np.nan), r2)
    if head_theta is None:
        head_theta = _protrusion_head(mesh, axis, c, u, v, thetas)
    allowed = np.ones_like(valid)
    if head_theta is not None and respect_head:
        opposite = head_theta + np.pi
        allowed = np.broadcast_to(angdist(thetas, opposite) <= np.pi / 2, valid.shape)
    if head_theta is not None:
        hd = math.cos(head_theta) * u + math.sin(head_theta) * v
        warnings.append(
            f"cabeza/setting detectada hacia {np.round(hd, 2).tolist()} (frame del STL): "
            + ("attach restringido al lado opuesto" if respect_head else "solo lleva feeder si es un hot spot aislado")
        )

    cand = eroded & allowed
    feats_common = dict(
        axis=axis.tolist(),
        axis_source=ax["source"],
        center=c.tolist(),
        com=mesh.center_mass.tolist(),
        volume_mm3=float(mesh.volume),
        bbox=mesh.bounds.tolist(),
        band_width_mm=width,
        inner_radius_mm=float(ax["r_fit"]),
        inner_radius_min_mm=float(np.nanmin(r1)) if np.isfinite(r1).any() else float(ax["r_fit"]),
        outer_radius_max_mm=float(np.nanmax(r2)) if np.isfinite(r2).any() else float("nan"),
        inner_thickness_max_mm=float(np.nanmax(thick[ok])) if ok.any() else 0.0,
        tunnel_open_frac=float(ax["open_frac"]),
        scan=dict(
            n_theta=N_THETA,
            n_h=int(n_h),
            h_range=[float(hs[0]), float(hs[-1])],
            clean_frac=float(ok.mean()),
            thick_ok_frac=float(valid.mean()),
            attachable_frac=float(cand.mean()),
            thickness_median_mm=float(np.nanmedian(thick[ok])) if ok.any() else 0.0,
        ),
        head_detected=head_theta is not None,
        head_theta_deg=None if head_theta is None else math.degrees(head_theta),
    )

    if not cand.any():
        raise FeatureError(
            f"no hay attach interno ≥ {t_min} mm de espesor "
            f"(espesor máx. medido {feats_common['inner_thickness_max_mm']:.2f} mm). "
            "Engrosa el shank por dentro o usa manual_attach en job.json."
        )

    # ranking: 1) espesor (con tolerancia), 2) cerca de la zona baja preferida, 3) cerca del lado opuesto a la cabeza
    feeder_r_est = min(max(t_min * profile.feeder_d_factor, profile.feeder_d_min_mm), profile.feeder_d_max_mm) / 2
    h_pref = min((hmin + hmax) / 2, hmin + feeder_r_est + 0.3)
    th_pref = (head_theta + np.pi) if head_theta is not None else -np.pi / 2
    idx = np.argwhere(cand)
    t_vals = thick[cand]
    score = (
        -np.round(t_vals / THICK_TOL)  # bins de espesor
        + 0.01 * np.abs(hs[idx[:, 0]] - h_pref)
        + 0.001 * angdist(thetas[idx[:, 1]], th_pref)
    )
    order = np.argsort(score, kind="stable")
    candidates = []
    for k in order[:max_candidates]:
        i, j = idx[k]
        d = math.cos(thetas[j]) * u + math.sin(thetas[j]) * v
        p = c + hs[i] * axis + r1[i, j] * d
        candidates.append(
            Candidate(
                point=p.tolist(),
                theta_deg=math.degrees(thetas[j]),
                h_mm=float(hs[i]),
                r_inner_mm=float(r1[i, j]),
                r_outer_mm=float(r2[i, j]),
                thickness_mm=float(thick[i, j]),
            )
        )
    if ax["open_frac"] < 1.0:
        warnings.append(f"túnel del dedo {ax['open_frac']:.0%} abierto (algo cruza el hueco)")
    return Features(**feats_common, candidates=candidates, warnings=warnings)


def probe(mesh, feats: Features, theta: float, h: float):
    """Un rayo desde el eje en (theta, h): devuelve (r1, r2, n_hits)."""
    axis = np.array(feats.axis)
    c = np.array(feats.center)
    u, v = plane_basis(axis)
    d = math.cos(theta) * u + math.sin(theta) * v
    hits = ray_hits(mesh, (c + h * axis)[None], d[None])[0]
    r1 = hits[0] if len(hits) >= 1 else float("nan")
    r2 = hits[1] if len(hits) >= 2 else float("nan")
    return r1, r2, len(hits)


def manual_candidate(mesh, feats: Features, point, profile: Profile) -> Candidate:
    """Proyecta manual_attach a la cara interna en su (theta, h) y valida keepout."""
    axis = np.array(feats.axis)
    c = np.array(feats.center)
    u, v = plane_basis(axis)
    p = np.asarray(point, float)
    q = p - c
    h = float(q @ axis)
    theta = math.atan2(float(q @ v), float(q @ u))
    r_pt = math.hypot(float(q @ u), float(q @ v))
    r1, r2, n = probe(mesh, feats, theta, h)
    if n < 2 or not np.isfinite(r2):
        raise FeatureError(
            f"manual_attach {list(p)} no cae sobre el shank (el rayo desde el eje no cruza metal)."
        )
    if "outer_surface" in profile.keepout and abs(r_pt - r2) < abs(r_pt - r1):
        raise FeatureError(
            f"manual_attach {list(p)} está en la cara EXTERNA (r={r_pt:.2f}, interna={r1:.2f}, "
            f"externa={r2:.2f}); el attach solo puede ir por dentro."
        )
    t = r2 - r1
    if "lattice_thin" in profile.keepout and t < profile.min_attach_thickness_mm:
        raise FeatureError(
            f"manual_attach: espesor local {t:.2f} mm < {profile.min_attach_thickness_mm} mm (lattice/filigrana)."
        )
    d = math.cos(theta) * u + math.sin(theta) * v
    return Candidate(
        point=(c + h * axis + r1 * d).tolist(),
        theta_deg=math.degrees(theta),
        h_mm=h,
        r_inner_mm=r1,
        r_outer_mm=r2,
        thickness_mm=t,
    )


class OuterGrid:
    """Radio de la cara externa (último hit) en una grilla fina (theta, h), frame de entrada."""

    def __init__(self, mesh, feats: Features, d_theta_deg: float = 1.0, h_step: float = 0.2):
        self.axis = np.array(feats.axis)
        self.c = np.array(feats.center)
        self.u, self.v = plane_basis(self.axis)
        hmin = float(((mesh.vertices - self.c) @ self.axis).min())
        hmax = float(((mesh.vertices - self.c) @ self.axis).max())
        n_h = max(2, int(math.ceil((hmax - hmin) / h_step)) + 1)
        self.hs = np.linspace(hmin + 0.02, hmax - 0.02, n_h)
        self.thetas = np.radians(np.arange(0.0, 360.0, d_theta_deg))
        H, T = np.meshgrid(self.hs, self.thetas, indexing="ij")
        self.origins = self.c + np.outer(H.ravel(), self.axis)
        self.dirs = np.outer(np.cos(T).ravel(), self.u) + np.outer(np.sin(T).ravel(), self.v)
        hits = ray_hits(mesh, self.origins, self.dirs)
        self.last = np.array([h[-1] if h else np.nan for h in hits]).reshape(H.shape)

    def min_clearance(self, sprue) -> float:
        """min(radio externo - radio máx. del sprue) sobre los rayos que tocan el sprue (inf si ninguno)."""
        q = sprue.vertices - self.c
        h = q @ self.axis
        th = np.arctan2(q @ self.v, q @ self.u) % (2 * np.pi)
        ih = (self.hs >= h.min() - 0.3) & (self.hs <= h.max() + 0.3)
        if not ih.any():
            return float("inf")
        # ventana angular (circular) que cubre el sprue
        d = np.diff(np.sort(th))
        gaps = np.r_[d, np.sort(th)[0] + 2 * np.pi - np.sort(th)[-1]]
        if gaps.max() > np.pi:  # sprue compacto: ventana alrededor de su media circular
            mid = math.atan2(np.sin(th).mean(), np.cos(th).mean())
            half = float(angdist(th, mid).max()) + math.radians(2)
            it = angdist(self.thetas, mid) <= half
        else:
            it = np.ones(len(self.thetas), bool)
        I, J = np.meshgrid(np.where(ih)[0], np.where(it)[0], indexing="ij")
        I, J = I.ravel(), J.ravel()
        flat = I * len(self.thetas) + J
        hits = ray_hits(sprue, self.origins[flat], self.dirs[flat])
        worst = float("inf")
        for k, hl in enumerate(hits):
            if not hl:
                continue
            ro = self.last[I[k], J[k]]
            if np.isnan(ro):
                continue
            worst = min(worst, ro - hl[-1])
        return worst
