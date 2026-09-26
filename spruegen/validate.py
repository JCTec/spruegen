"""Validación del STL final (y de la proposal que lo generó)."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import trimesh

from . import io, repair
from .build import ring_in_job_frame
from .features import ray_hits
from .policy import check_locks
from .schemas import InputError, Profile, Proposal

OUTER_TOL_MM = 0.05


def load_ring_job(prop: Proposal) -> trimesh.Trimesh:
    """Anillo en el frame del job, reconstruido desde el STL de entrada (verificando hash)."""
    src = Path(prop.input["path"])
    if src.exists():
        if io.sha256(src) != prop.input["sha256"]:
            raise InputError(f"el STL de entrada cambió desde el propose ({src}); vuelve a correr propose.")
        mesh, _ = repair.repair(io.load_stl(src))
        return ring_in_job_frame(mesh, prop.transform)
    prev = Path(prop.previews.get("ring", ""))
    if prev.exists():
        return io.load_stl(prev)
    raise InputError(f"no encuentro el STL de entrada ({src}) ni preview_ring.stl")


def _axis_section_area(mesh, z, r_max=None):
    """Área del polígono de la sección z que contiene el eje (0, 0) (el stem), en coords del mundo."""
    import shapely

    sec = mesh.section(plane_origin=[0, 0, z], plane_normal=[0, 0, 1])
    if sec is None:
        return 0.0, None
    planar, to3d = sec.to_2D()
    for poly in planar.polygons_full:
        ext = np.asarray(poly.exterior.coords)
        pts = np.c_[ext, np.zeros(len(ext)), np.ones(len(ext))]
        xy = (to3d @ pts.T).T[:, :2]
        holes = []
        for ring in poly.interiors:
            hc = np.asarray(ring.coords)
            holes.append((to3d @ np.c_[hc, np.zeros(len(hc)), np.ones(len(hc))].T).T[:, :2])
        world = shapely.Polygon(xy, holes)
        if world.contains(shapely.Point(0.0, 0.0)):
            return float(world.area), (float(world.area), xy)
    return 0.0, None


def measure_stem(mesh: trimesh.Trimesh, h_expected: float, d_expected: float) -> dict:
    """Mide Ø y alto del stem por slices (base en z=min del mesh)."""
    z0 = float(mesh.bounds[0, 2])
    r_max = d_expected  # centroides de polígonos cerca del eje
    z_mid = z0 + h_expected / 2
    a_mid, poly = _axis_section_area(mesh, z_mid, r_max)
    if poly is None or a_mid <= 0:
        return {"ok": False, "reason": "no hay sección de stem sobre el eje"}
    xy = poly[1]
    ext = xy.max(0) - xy.min(0)
    d = float(ext.mean())

    def is_stem(z):
        a, _ = _axis_section_area(mesh, z, r_max)
        return a >= 0.85 * a_mid

    z_hi_limit = float(mesh.bounds[1, 2])
    lo, step = z_mid, 0.5
    hi = None
    z = lo
    while z < z_hi_limit:
        z = min(z + step, z_hi_limit)
        if not is_stem(z):
            hi = z
            break
        lo = z
    if hi is None:
        hi = z_hi_limit
    for _ in range(12):
        m = (lo + hi) / 2
        if is_stem(m):
            lo = m
        else:
            hi = m
    return {"ok": True, "d_mm": d, "h_mm": (lo + hi) / 2 - z0, "z_base": z0, "area_mid": a_mid}


def _sunflower(n, r):
    k = np.arange(n) + 0.5
    rr = r * np.sqrt(k / n)
    t = k * math.pi * (3 - math.sqrt(5))
    return np.c_[rr * np.cos(t), rr * np.sin(t)]


def hole_block_frac(mesh, r_test, z0, z1, n=240) -> float:
    xy = _sunflower(n, r_test)
    origins = np.c_[xy, np.full(n, z0 - 1e-3)]
    hits = ray_hits(mesh, origins, np.tile([0.0, 0.0, 1.0], (n, 1)))
    span = z1 - z0
    return sum(1 for h in hits if any(d < span for d in h)) / n


def outer_surface_diff(ring, out, z0, z1, n_theta=90, n_z=9) -> float:
    """Máx. diferencia del último hit radial (cara externa) entre anillo solo y resultado.

    Los rayos que rozan una arista pueden registrar hit en una malla y no en la otra (retriangulada):
    esos se re-lanzan con un pequeño corrimiento y cuenta el mejor de los intentos.
    """
    th = np.linspace(0, 2 * np.pi, n_theta, endpoint=False) + 0.0071
    zs = np.linspace(z0 + 0.2, z1 - 0.2, n_z) + 0.0037 if z1 - z0 > 0.5 else np.array([(z0 + z1) / 2])

    def diffs(dz, dth):
        Z, T = np.meshgrid(zs + dz, th + dth, indexing="ij")
        origins = np.c_[np.zeros(Z.size), np.zeros(Z.size), Z.ravel()]
        dirs = np.c_[np.cos(T.ravel()), np.sin(T.ravel()), np.zeros(Z.size)]
        hr = ray_hits(ring, origins, dirs)
        ho = ray_hits(out, origins, dirs)
        d = np.zeros(len(hr))
        for i, (a, b) in enumerate(zip(hr, ho)):
            if not a:
                continue
            d[i] = float("inf") if not b else abs(a[-1] - b[-1])
        return d

    best = diffs(0.0, 0.0)
    for dz, dth in ((0.011, 0.0013), (-0.013, -0.0017)):
        if not np.any(best > OUTER_TOL_MM):
            break
        best = np.minimum(best, diffs(dz, dth))
    return float(best.max()) if len(best) else 0.0


def validate(
    out: trimesh.Trimesh,
    prop: Proposal | None = None,
    ring_job: trimesh.Trimesh | None = None,
    profile: Profile | None = None,
) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    metrics: dict = {"volume_mm3": float(out.volume), "watertight": bool(out.is_watertight)}
    p = prop.profile if prop is not None else (profile or Profile())

    if not out.is_watertight:
        errors.append("la malla final no es watertight")

    # --- stem
    d_exp, h_exp = (prop.stem.d_mm, prop.stem.h_mm) if prop else (p.stem_d_mm, p.stem_h_mm)
    if (d_exp, h_exp) != (10.0, 35.0):
        warnings.append(f"stem con override explícito: Ø{d_exp} x {h_exp} mm (estándar Ø10 x 35)")
    st = measure_stem(out, h_exp, d_exp)
    metrics["stem"] = st
    if not st["ok"]:
        errors.append(f"no se pudo medir el stem: {st['reason']}")
    else:
        if abs(st["d_mm"] - d_exp) > p.stem_d_tol_mm:
            errors.append(f"stem mide Ø{st['d_mm']:.2f} mm (esperado {d_exp}±{p.stem_d_tol_mm})")
        if abs(st["h_mm"] - h_exp) > p.stem_h_tol_mm:
            errors.append(f"stem mide {st['h_mm']:.2f} mm de alto (esperado {h_exp}±{p.stem_h_tol_mm})")

    if prop is None:
        warnings.append("sin --proposal solo se validan watertight y stem")
        return {"ok": not errors, "errors": errors, "warnings": warnings, "metrics": metrics}

    if ring_job is None:
        ring_job = load_ring_job(prop)
    rz0, rz1 = (float(x) for x in ring_job.bounds[:, 2])
    ring_vol = float(ring_job.volume)
    metrics["ring_volume_mm3"] = ring_vol
    if out.volume <= ring_vol + 1e-3:
        errors.append(f"volumen final {out.volume:.2f} ≤ volumen del anillo {ring_vol:.2f}: no se pegó nada")

    # --- hueco del dedo
    r_in = prop.ring_job["r_inner_min_mm"]
    frac = hole_block_frac(out, p.hole_test_radius_frac * r_in, rz0, rz1)
    metrics["hole_blocked_frac"] = frac
    if frac > p.hole_block_max_frac:
        errors.append(
            f"el sprue tapa el hueco del dedo: {frac:.0%} del cilindro de prueba "
            f"(r={p.hole_test_radius_frac * r_in:.2f} mm) bloqueado"
        )

    # --- cada attach: más cerca de la cara interna que de la externa
    attach_metrics = []
    for k, f in enumerate(prop.feeders):
        A = np.array(f.attach)
        rdir = np.array([A[0], A[1], 0.0])
        rdir = rdir / max(np.linalg.norm(rdir), 1e-9)
        hits = ray_hits(ring_job, np.array([[0.0, 0.0, A[2]]]), rdir[None])[0]
        tip_r = min(float(np.hypot(*np.array(f.end)[:2])), f.clip_r_mm)
        if len(hits) < 2:
            errors.append(f"feeder #{k + 1}: en el punto de attach no hay shank (rayo desde el eje no cruza metal)")
            continue
        r1, r2 = hits[0], hits[1]
        attach_metrics.append({"r_inner": r1, "r_outer": r2, "tip_r": tip_r})
        if abs(tip_r - r2) <= abs(tip_r - r1):
            errors.append(
                f"feeder #{k + 1}: attach más cerca de la cara externa (tip r={tip_r:.2f}, int={r1:.2f}, ext={r2:.2f})"
            )
    metrics["attach"] = attach_metrics[0] if len(attach_metrics) == 1 else attach_metrics
    metrics["feeders"] = len(prop.feeders)
    if prop.attach.thickness_mm < p.min_attach_thickness_mm + 0.2:
        warnings.append(f"espesor en el attach {prop.attach.thickness_mm:.2f} mm, justo en el mínimo")

    # --- todo pegado: una sola pieza
    bodies = int(out.body_count)
    metrics["bodies"] = bodies
    if bodies != 1:
        errors.append(f"la malla final tiene {bodies} cuerpos: algo del árbol o una varilla quedó suelta")

    # --- troncos de las Y: área >= suma de los brazos (gating)
    for b in prop.branches:
        arms = sum((prop.feeders[i].d_mm / 2) ** 2 for i in b.arms)
        if (b.d_mm / 2) ** 2 < arms * 0.98:
            warnings.append(f"tronco Ø{b.d_mm:.2f} mm con menos área que sus brazos (limitado por trunk_d_max_mm)")
    if prop.profile.tree.uniform and len(prop.feeders) > 1:
        Ls = [f.len_mm for f in prop.feeders if f.node_kind == "stem"]
        if len(Ls) > 1 and max(Ls) - min(Ls) > 1.0:
            warnings.append(f"feeders directos con largos dispares ({min(Ls):.1f}–{max(Ls):.1f} mm)")

    # --- varillas: en el canto lejano, por dentro
    for k, v in enumerate(prop.vents):
        base, top_v = np.array(v.base), np.array(v.top)
        if top_v[2] - base[2] < v.d_mm:
            errors.append(f"varilla #{k + 1} degenerada")
        r_v = float(np.hypot(*base[:2]))
        if r_v - v.d_mm / 2 > v.clip_r_mm:
            errors.append(f"varilla #{k + 1} fuera de la cara interna")

    # --- cara externa intacta
    diff = outer_surface_diff(ring_job, out, rz0, rz1)
    metrics["outer_surface_max_diff_mm"] = diff
    if "outer_surface" in p.keepout and diff > OUTER_TOL_MM:
        errors.append(f"la cara externa del anillo cambió (hasta {diff:.2f} mm): el sprue la toca")

    # --- espacio de pieza
    top = float(out.bounds[1, 2])
    piece = top - prop.stem.h_mm  # incluye varillas
    metrics["piece_height_mm"] = piece
    if piece > p.ring_space_mm:
        errors.append(f"la pieza mide {piece:.1f} mm sobre el stem > ring_space_mm {p.ring_space_mm}")

    # --- locks
    bad = check_locks(prop.locks.get("values", {}), prop.stem, prop.profile)
    if st.get("ok"):
        for k, meas in (("stem_d_mm", st["d_mm"]), ("stem_h_mm", st["h_mm"])):
            lv = prop.locks.get("values", {}).get(k)
            tol = p.stem_d_tol_mm if k == "stem_d_mm" else p.stem_h_tol_mm
            if lv is not None and abs(meas - lv) > tol:
                bad.append(f"{k}: bloqueado={lv}, medido={meas:.2f}")
    if bad or not prop.locks_honored:
        errors.append("locks violados: " + ("; ".join(bad) if bad else "locks_honored=false"))

    for k, f in enumerate(prop.feeders):
        if f.len_mm > 12.0:
            warnings.append(f"feeder #{k + 1} de {f.len_mm:.1f} mm (> 12 mm)")
    if prop.input.get("repair", {}).get("normals_fixed"):
        warnings.append("el STL de entrada tenía normales/winding raros (ya reparados)")

    return {"ok": not errors, "errors": errors, "warnings": warnings, "metrics": metrics}
