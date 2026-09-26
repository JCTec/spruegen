"""¿Cuántos feeders y dónde? Análisis geométrico de alimentación (sin CFD, determinista).

1. Módulo térmico: EDT del anillo voxelizado (zonas gruesas = hot spots que solidifican al final).
2. Una celda está *alimentada* por un attach si:
     - el cuello más ancho del camino (maximin) >= neck_ratio * módulo(celda)   (solidificación direccional)
     - el camino geodésico por el metal <= feed_reach_mm
3. Set cover greedy sobre los candidatos internos válidos (los mismos de v0.1), primero fuera de la cabeza.
4. Mínimo por capacidad: ceil(volumen / feeder_capacity_mm3).
5. Preferencia de simetría: con k feeders, prueba repartos parejos y los usa si cubren casi lo mismo.
6. Zonas aisladas (nadie las alimenta) -> warning accionable.
7. Última en llenarse: distancia geodésica máxima desde los feeders -> lugar de las varillas de venteo.

Los parámetros son valores de partida: calíbralos con `spruegen log` y tus coladas.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

import numpy as np
import trimesh
from scipy import sparse

from . import voxel
from .features import angdist, plane_basis
from .schemas import Candidate, Features, Profile
from .tree import alternates_for

BIN_DEG = 5.0
COVER_TARGET = 0.99


@dataclass
class AnalysisResult:
    summary: dict
    attaches: list[Candidate]
    alternates: list[list[Candidate]]
    pool: list[Candidate]
    graph: voxel.CellGraph
    field: voxel.VoxelField
    fed_by: np.ndarray  # por celda: índice de feeder que la alimenta (-1 = aislada)
    fill_dist: np.ndarray  # por celda: distancia geodésica al feeder más cercano
    cell_theta: np.ndarray
    cell_h: np.ndarray
    vent_targets: list[dict] = field(default_factory=list)


def thin_pool(pool: list[Candidate], bin_deg: float = BIN_DEG) -> list[Candidate]:
    """Un candidato por sector angular (el mejor rankeado), para que el set cover sea barato y parejo."""
    seen: set[int] = set()
    out = []
    for c in pool:
        b = int((c.theta_deg % 360.0) // bin_deg)
        if b not in seen:
            seen.add(b)
            out.append(c)
    return out


def _cand_cell(g, feats: Features, c: Candidate) -> int:
    axis = np.array(feats.axis)
    ctr = np.array(feats.center)
    p = np.array(c.point)
    q = p - ctr
    radial = q - (q @ axis) * axis
    rhat = radial / max(np.linalg.norm(radial), 1e-9)
    # fuente = centro de la sección detrás del attach (el feeder alimenta lo más grueso de esa sección)
    return voxel.nearest_cell(g, p + rhat * (c.thickness_mm / 2))


def _components(g, mask: np.ndarray) -> list[np.ndarray]:
    idx = np.where(mask)[0]
    if not len(idx):
        return []
    sub = g.length[idx][:, idx]
    n, lab = sparse.csgraph.connected_components(sub, directed=False)
    return [idx[lab == k] for k in range(n)]


def analyze(mesh: trimesh.Trimesh, feats: Features, pool: list[Candidate], p: Profile) -> AnalysisResult:
    t0 = time.time()
    tc = p.tree
    warnings: list[str] = []
    pitch = tc.voxel_mm or voxel.pitch_for(float(np.max(mesh.extents)))
    vf = voxel.voxelize(mesh, pitch)
    g = voxel.cell_graph(vf, voxel.cell_size_for(float(mesh.volume)))
    m = g.modulus
    n_cells = len(m)

    axis = np.array(feats.axis)
    ctr = np.array(feats.center)
    u, v = plane_basis(axis)
    q = g.centers - ctr
    cell_h = q @ axis
    cell_th = np.arctan2(q @ v, q @ u)

    cands = thin_pool(pool)
    if not cands:
        raise ValueError("sin candidatos")
    head = math.radians(feats.head_theta_deg) if feats.head_theta_deg is not None else None
    is_head = np.array(
        [head is not None and float(angdist(math.radians(c.theta_deg), head)) < math.radians(60) for c in cands]
    )
    cells = np.array([_cand_cell(g, feats, c) for c in cands])
    D = voxel.geodesic_from(g, cells)
    W = np.vstack([voxel.widest_path_from(g, int(cl)) for cl in cells])
    fed = (W >= tc.neck_ratio * m[None, :] - 1e-9) & (D <= tc.feed_reach_mm)
    w = g.volume * (0.25 + m / max(m.max(), 1e-9))  # pesa más lo grueso
    total = float(w.sum())

    def coverage(sel) -> float:
        if not len(sel):
            return 0.0
        return float(w[np.any(fed[list(sel)], axis=0)].sum() / total)

    # --- greedy (primero fuera de la cabeza; la cabeza solo si queda algo sin alimentar)
    chosen: list[int] = []
    covered = np.zeros(n_cells, bool)
    used_head = False
    for allow_head in (False, True):
        if allow_head and (1 - w[covered].sum() / total) <= 1 - COVER_TARGET:
            break
        while len(chosen) < tc.max_feeders:
            if w[covered].sum() / total >= COVER_TARGET:
                break
            gains = np.array(
                [
                    -1.0 if (i in chosen or (is_head[i] and not allow_head)) else float(w[fed[i] & ~covered].sum())
                    for i in range(len(cands))
                ]
            )
            best = int(np.argmax(gains))
            # un feeder extra solo si alimenta algo que valga la pena (no micro hot spots del lattice)
            if gains[best] <= (tc.min_gain_frac * total if chosen else 1e-9 * total):
                break
            chosen.append(best)
            covered |= fed[best]
            used_head |= bool(is_head[best])
    # reverse delete: quitar feeders que ya no aportan (p. ej. el del shank cuando el de la cabeza cubre todo)
    for i in list(chosen)[::-1]:
        rest = [j for j in chosen if j != i]
        if rest and coverage(rest) >= coverage(chosen) - 0.005:
            chosen = rest
    used_head = bool(any(is_head[i] for i in chosen))
    k_greedy = len(chosen)
    cov_greedy = coverage(chosen)

    k_cap = max(1, math.ceil(float(mesh.volume) / tc.feeder_capacity_mm3))
    k = tc.feeders or min(max(k_greedy, k_cap), tc.max_feeders)
    reasons = [
        f"cobertura: {k_greedy} feeder(s) alimentan {cov_greedy:.0%} (cuello ≥ {tc.neck_ratio}×módulo, "
        f"alcance ≤ {tc.feed_reach_mm:g} mm)",
        f"capacidad: volumen {mesh.volume:.0f} mm³ / {tc.feeder_capacity_mm3:g} mm³ por feeder → mínimo {k_cap}",
    ]
    if tc.feeders:
        reasons.append(f"cantidad forzada por el profile/CLI: {tc.feeders}")

    # --- preferencia de simetría / completar hasta k
    allowed = [i for i in range(len(cands)) if used_head or not is_head[i]]
    sym_used = False
    if k >= 2 and (tc.prefer_symmetry or k > k_greedy):
        ref = cands[chosen[0]].theta_deg if chosen else cands[0].theta_deg
        best_sym = None
        for off in np.arange(0.0, 360.0 / k, 5.0):
            sel = []
            for j in range(k):
                tgt = math.radians(ref + off + j * 360.0 / k)
                near = [
                    i for i in allowed
                    if i not in sel and float(angdist(math.radians(cands[i].theta_deg), tgt))
                    <= math.radians(tc.angle_tolerance_deg)
                ]
                if not near:
                    break
                sel.append(min(near, key=lambda i: (-round(cands[i].thickness_mm / 0.15),
                                                     float(angdist(math.radians(cands[i].theta_deg), tgt)))))
            if len(sel) < k:
                continue
            key = (round(coverage(sel), 3), min(cands[i].thickness_mm for i in sel))
            if best_sym is None or key > best_sym[0]:
                best_sym = (key, sel)
        if best_sym is not None and (k > k_greedy or best_sym[0][0] >= cov_greedy - 0.01):
            chosen, sym_used = best_sym[1], True
        elif k > k_greedy:
            # completar lo más separado posible de los elegidos
            while len(chosen) < k:
                rest = [i for i in allowed if i not in chosen]
                if not rest:
                    break
                far = max(rest, key=lambda i: min(float(angdist(math.radians(cands[i].theta_deg),
                                                               math.radians(cands[j].theta_deg))) for j in chosen))
                chosen.append(far)
    elif k < len(chosen):
        chosen = chosen[:k]

    # primario = el que más alimenta
    chosen.sort(key=lambda i: -float(w[fed[i]].sum()))
    cov = coverage(chosen)
    sel = np.array(chosen)
    fed_sel = fed[sel]
    Dsel = np.where(fed_sel, D[sel], np.inf)
    fed_by = np.where(np.isfinite(Dsel.min(0)), np.argmin(Dsel, axis=0), -1)
    fill_dist = D[sel].min(0)

    # --- zonas aisladas
    zones = []
    for comp in _components(g, fed_by < 0):
        vol = float(g.volume[comp].sum())
        if vol < 2.0:
            continue
        th = float(np.degrees(math.atan2(np.sin(cell_th[comp]).mean(), np.cos(cell_th[comp]).mean())))
        zones.append({
            "volume_mm3": vol,
            "max_modulus_mm": float(m[comp].max()),
            "theta_deg": th,
            "h_mm": float(cell_h[comp].mean()),
        })
    for z in zones:
        warnings.append(
            f"zona aislada de {z['volume_mm3']:.1f} mm³ cerca de theta={z['theta_deg']:.0f}° "
            f"(módulo {z['max_modulus_mm']:.2f} mm): puede quedar porosa; engrosa el puente o agrega un feeder manual"
        )

    # --- hot spots (máximos de módulo separados)
    hot = []
    for i in np.argsort(-m):
        if len(hot) >= 5:
            break
        if all(float(angdist(cell_th[i], math.radians(hh["theta_deg"]))) > math.radians(20) for hh in hot):
            hot.append({"theta_deg": float(np.degrees(cell_th[i])), "h_mm": float(cell_h[i]), "modulus_mm": float(m[i])})

    # --- última en llenarse -> varillas
    vent_targets = []
    finite = np.isfinite(fill_dist)
    for i in np.argsort(-np.where(finite, fill_dist, -1)):
        if not finite[i] or len(vent_targets) >= max(p.vents.count, 4):
            break
        if all(float(angdist(cell_th[i], math.radians(vt["theta_deg"]))) >= math.radians(p.vents.min_sep_deg)
               for vt in vent_targets):
            vent_targets.append({"theta_deg": float(np.degrees(cell_th[i])), "h_mm": float(cell_h[i]),
                                 "fill_dist_mm": float(fill_dist[i])})

    attaches = [cands[i] for i in chosen]
    alternates = [alternates_for(c.theta_deg, pool, tc.angle_tolerance_deg, exclude=attaches) for c in attaches]
    per_feeder = []
    for j, i in enumerate(chosen):
        c = cands[i]
        per_feeder.append({
            "theta_deg": c.theta_deg, "h_mm": c.h_mm, "thickness_mm": c.thickness_mm, "head": bool(is_head[i]),
            "feeds_volume_frac": float(g.volume[fed_by == j].sum() / g.volume.sum()),
        })
    if used_head:
        reasons.append("la cabeza es un hot spot aislado: lleva su propio feeder por la cara interna")
    if sym_used:
        reasons.append("reparto simétrico (cubre casi lo mismo que el greedy y equilibra el flujo)")

    summary = {
        "params": {
            "voxel_mm": pitch, "cell_mm": g.cell_size, "neck_ratio": tc.neck_ratio,
            "feed_reach_mm": tc.feed_reach_mm, "feeder_capacity_mm3": tc.feeder_capacity_mm3,
        },
        "n_cells": int(n_cells),
        "volume_mm3": float(mesh.volume),
        "voxel_volume_mm3": float(g.volume.sum()),
        "modulus_mm": {"min": float(m.min()), "median": float(np.median(m)), "max": float(m.max())},
        "hot_spots": hot,
        "k_greedy": k_greedy,
        "k_capacity": k_cap,
        "feeder_count": len(chosen),
        "symmetric": sym_used,
        "coverage": cov,
        "coverage_volume": float(g.volume[fed_by >= 0].sum() / g.volume.sum()),
        "feeders": per_feeder,
        "isolated_zones": zones,
        "last_to_fill": vent_targets,
        "reasons": reasons,
        "warnings": warnings,
        "seconds": round(time.time() - t0, 2),
    }
    return AnalysisResult(
        summary=summary, attaches=attaches, alternates=alternates, pool=pool, graph=g, field=vf,
        fed_by=fed_by, fill_dist=fill_dist, cell_theta=cell_th, cell_h=cell_h, vent_targets=vent_targets,
    )


def zone_meshes(res: AnalysisResult) -> dict[str, trimesh.Trimesh]:
    """Una malla de cubitos por zona (feeder k / aislada), en el frame del STL: para colorear en el slicer."""
    g = res.graph
    out = {}
    labels = sorted(set(res.fed_by.tolist()))
    for lab in labels:
        idx = np.where(res.fed_by == lab)[0]
        if not len(idx):
            continue
        box = trimesh.creation.box(extents=[g.cell_size * 0.9] * 3)
        verts = (box.vertices[None, :, :] + g.centers[idx][:, None, :]).reshape(-1, 3)
        faces = (box.faces[None, :, :] + (np.arange(len(idx)) * len(box.vertices))[:, None, None]).reshape(-1, 3)
        name = "zone_isolated" if lab < 0 else f"zone_feeder{lab + 1}"
        out[name] = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
    return out
