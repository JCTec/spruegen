"""Carga/guardado de STL y chequeo de unidades."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

import numpy as np
import trimesh

from spruegen.schemas import InputError

# un anillo en mm mide ~15-40 mm de ancho; en pulgadas ~0.6-1.6
INCH_MAX_EXTENT = 3.0
MM_MAX_EXTENT = 150.0


def sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_stl(path: str | Path) -> trimesh.Trimesh:
    """Carga STL (binario o ASCII) como una sola malla, sin procesar."""
    path = Path(path)
    if not path.exists():
        raise InputError(f"no existe el STL: {path}")
    try:
        mesh = trimesh.load(str(path), file_type="stl", force="mesh", process=False)
    except Exception as e:  # trimesh lanza tipos variados
        raise InputError(f"no se pudo leer el STL {path}: {e}")
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
        raise InputError(f"el STL {path} no contiene triángulos")
    return mesh


def check_units(mesh: trimesh.Trimesh) -> None:
    """Asume milímetros; aborta si el tamaño sugiere pulgadas (o metros/micras)."""
    ext = float(np.max(mesh.extents))
    if ext < INCH_MAX_EXTENT:
        raise InputError(
            f"posible STL en pulgadas: el anillo mide {ext:.3f} unidades de ancho. "
            "spruegen asume milímetros; reexporta en mm (o escala x25.4)."
        )
    if ext > MM_MAX_EXTENT:
        raise InputError(
            f"el STL mide {ext:.1f} unidades: demasiado grande para un anillo en mm "
            "(¿exportado en micras o con otra escala?)."
        )


def save_stl_atomic(mesh: trimesh.Trimesh, path: str | Path) -> None:
    """Exporta STL binario vía archivo temporal + rename (nunca deja un archivo a medias)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".stl.tmp", dir=path.parent)
    os.close(fd)
    try:
        mesh.export(tmp, file_type="stl")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
