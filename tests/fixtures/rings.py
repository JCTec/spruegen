"""Anillos sintéticos para tests (mm). `python tests/fixtures/rings.py` los exporta como STL.

Los anillos "de galería" viven en spruegen.showcase; acá quedan los de tests puntuales.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import trimesh

from spruegen.showcase import carved_band, dumbbell_ring, lattice_band, plain_band, signet, solitaire, wide_band  # noqa: F401


def torus_ring(inner_d: float = 19.0, shank: float = 2.0) -> trimesh.Trimesh:
    """Torus: ID `inner_d`, sección redonda de diámetro `shank`. Eje del dedo = Z."""
    r = shank / 2
    return trimesh.creation.torus(major_radius=inner_d / 2 + r, minor_radius=r, major_sections=128, minor_sections=32)


def head_ring() -> trimesh.Trimesh:
    """Torus con una 'cabeza' (setting) sólida en +X."""
    ring = torus_ring(19.0, 2.4)
    head = trimesh.creation.box(extents=[5.0, 7.0, 5.0])
    head.apply_translation([13.0, 0.0, 0.0])
    return trimesh.boolean.union([ring, head], engine="manifold")


def tilted(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Copia rotada/trasladada arbitrariamente (el eje del dedo deja de ser Z)."""
    m = mesh.copy()
    m.apply_transform(trimesh.transformations.euler_matrix(0.7, -0.4, 1.1))
    m.apply_translation([3.0, -7.0, 12.0])
    return m


def open_torus() -> trimesh.Trimesh:
    """Torus con un parche de caras borrado: no watertight y no reparable."""
    m = torus_ring()
    keep = np.ones(len(m.faces), bool)
    c = m.triangles_center
    keep[(c[:, 0] > 9.0) & (np.abs(c[:, 1]) < 2.5)] = False
    m.update_faces(keep)
    return m


if __name__ == "__main__":
    out = Path(__file__).parent
    for name, fn in [("torus_19x2", torus_ring), ("carved_band", carved_band), ("head_ring", head_ring),
                     ("dumbbell", dumbbell_ring)]:
        fn().export(out / f"{name}.stl")
        print("->", out / f"{name}.stl")
