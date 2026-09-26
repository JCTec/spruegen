"""Reparación conservadora: merge, normales, huecos triviales. Si sigue abierto, falla."""

from __future__ import annotations

import numpy as np
import trimesh

from .schemas import InputError


def repair(mesh: trimesh.Trimesh) -> tuple[trimesh.Trimesh, dict]:
    """Devuelve (malla reparada, reporte). Lanza InputError si no queda watertight."""
    m = mesh.copy()
    report: dict = {"actions": [], "normals_fixed": False, "watertight_in": bool(mesh.is_watertight)}

    n_v = len(m.vertices)
    m.merge_vertices()
    if len(m.vertices) != n_v:
        report["actions"].append(f"merge_vertices ({n_v} -> {len(m.vertices)})")

    if not m.is_watertight:
        # solo si hace falta: quitar astillas de área cero en una malla ya cerrada abre agujeros
        n_f = len(m.faces)
        m.update_faces(m.nondegenerate_faces())
        m.update_faces(m.unique_faces())
        m.remove_unreferenced_vertices()
        if len(m.faces) != n_f:
            report["actions"].append(f"caras degeneradas/duplicadas eliminadas ({n_f} -> {len(m.faces)})")

    if not m.is_watertight:
        # astillas de exportación (float32): vértices a < 1 µm son el mismo punto
        t = m.copy()
        t.merge_vertices(digits_vertex=6)
        t.update_faces(t.nondegenerate_faces())
        t.update_faces(t.unique_faces())
        t.remove_unreferenced_vertices()
        if t.is_watertight:
            m = t
            report["actions"].append("vértices a < 1 µm fusionados (astillas de exportación)")

    if not m.is_watertight:
        trimesh.repair.fill_holes(m)
        report["actions"].append("fill_holes")

    if not m.is_watertight:
        raise InputError(
            "el STL no es watertight y la reparación automática no alcanza "
            f"({len(m.faces)} caras, bordes abiertos). Repáralo en tu CAD / Meshmixer; "
            "spruegen no inventa tapas."
        )

    was_consistent = bool(m.is_winding_consistent)
    vol_before = float(m.volume)
    trimesh.repair.fix_winding(m)
    trimesh.repair.fix_inversion(m)
    trimesh.repair.fix_normals(m)
    if not was_consistent or vol_before < 0:
        report["normals_fixed"] = True
        report["actions"].append("normales/winding corregidos")

    if m.body_count > 1:
        raise InputError(
            f"el STL contiene {m.body_count} cuerpos separados; v1 soporta un solo anillo "
            "de un cuerpo (une las piezas en tu CAD)."
        )
    if not (m.volume > 0 and np.isfinite(m.volume)):
        raise InputError("volumen no positivo tras reparar; revisa el STL.")
    return m, report
