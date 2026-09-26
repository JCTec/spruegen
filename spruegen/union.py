"""Unión booleana final (manifold3d) + limpieza para que sobreviva el round-trip a STL."""

from __future__ import annotations

import io as _io

import manifold3d
import numpy as np
import trimesh

from .schemas import SpruegenError

# tolerancias (mm) para colapsar astillas microscópicas que en STL (float32, sin topología) se funden
SIMPLIFY_TOLS = (1e-4, 1e-3, 5e-3)


def stl_roundtrip(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Lo que realmente verá el slicer: exporta a STL binario y vuelve a cargar (merge por posición)."""
    buf = _io.BytesIO(mesh.export(file_type="stl"))
    return trimesh.load(buf, file_type="stl", force="mesh")


def _simplify(mesh: trimesh.Trimesh, tol: float) -> trimesh.Trimesh:
    man = manifold3d.Manifold(
        manifold3d.Mesh(
            vert_properties=np.asarray(mesh.vertices, np.float32),
            tri_verts=np.asarray(mesh.faces, np.uint32),
        )
    ).simplify(tol)
    out = man.to_mesh()
    return trimesh.Trimesh(vertices=np.asarray(out.vert_properties)[:, :3], faces=out.tri_verts, process=True)


def union(parts: list[trimesh.Trimesh]) -> trimesh.Trimesh:
    try:
        out = trimesh.boolean.union(parts, engine="manifold")
    except Exception as e:
        raise SpruegenError(f"falló el boolean (manifold): {e}")
    if not isinstance(out, trimesh.Trimesh) or len(out.faces) == 0:
        raise SpruegenError("el boolean devolvió una malla vacía")
    if not out.is_watertight:
        raise SpruegenError("la unión no quedó watertight")

    if not stl_roundtrip(out).is_watertight:
        for tol in SIMPLIFY_TOLS:
            cand = _simplify(out, tol)
            if cand.is_watertight and stl_roundtrip(cand).is_watertight:
                out = cand
                break
        else:
            raise SpruegenError("la unión no sobrevive la exportación a STL (astillas no manifold)")

    vol_sum = sum(p.volume for p in parts)
    vol_max = max(p.volume for p in parts)
    if not (vol_max - 1e-2 < out.volume <= vol_sum + 1e-2):
        raise SpruegenError(
            f"volumen de la unión incoherente: {out.volume:.2f} mm³ (partes: suma {vol_sum:.2f}, mayor {vol_max:.2f})"
        )
    return out


def stl_safe(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Devuelve una malla que sigue watertight tras exportarse a STL (float32, sin topología)."""
    if stl_roundtrip(mesh).is_watertight:
        return mesh
    for tol in SIMPLIFY_TOLS:
        cand = _simplify(mesh, tol)
        if cand.is_watertight and stl_roundtrip(cand).is_watertight:
            return cand
    raise SpruegenError("la malla no sobrevive la exportación a STL (astillas no manifold)")
