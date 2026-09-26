"""Campo de módulo térmico por voxels + grafo de celdas para el análisis de alimentación.

Módulo (Chvorinov): tiempo de solidificación ~ (V/A)^2. En una placa de espesor t, V/A = t/2, que es
justo la distancia al borde más lejana (EDT). Usamos la EDT del volumen voxelizado como proxy de módulo:
zonas con EDT alto = "hot spots" que solidifican al final.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import shapely
import trimesh
from scipy import ndimage, sparse


@dataclass
class VoxelField:
    origin: np.ndarray  # centro del voxel [0,0,0]
    pitch: float
    occ: np.ndarray  # bool (nx, ny, nz)
    edt: np.ndarray  # mm, 0 fuera

    def centers(self, idx: np.ndarray) -> np.ndarray:
        return self.origin + idx * self.pitch


def voxelize(mesh: trimesh.Trimesh, pitch: float = 0.15) -> VoxelField:
    """Rasteriza por slices (exacto en los centros de voxel; sin inflar la superficie)."""
    lo, hi = mesh.bounds
    origin = lo + pitch / 2
    n = np.maximum(np.ceil((hi - lo) / pitch).astype(int), 1)
    xs = origin[0] + np.arange(n[0]) * pitch
    ys = origin[1] + np.arange(n[1]) * pitch
    zs = origin[2] + np.arange(n[2]) * pitch
    X, Y = np.meshgrid(xs, ys, indexing="ij")
    occ = np.zeros(n, bool)
    heights = zs - lo[2]
    secs = mesh.section_multiplane(plane_origin=[0, 0, lo[2]], plane_normal=[0, 0, 1], heights=heights)
    for k, sec in enumerate(secs):
        if sec is None:
            continue
        # section_multiplane devuelve Path2D en coords XY del mundo (plano normal a Z, origen en z)
        polys = [p for p in sec.polygons_full if p is not None and p.area > 0]
        if not polys:
            continue
        geom = shapely.union_all(polys) if len(polys) > 1 else polys[0]
        occ[:, :, k] = shapely.contains_xy(geom, X, Y)
    padded = np.pad(occ, 1)
    edt = ndimage.distance_transform_edt(padded)[1:-1, 1:-1, 1:-1] * pitch
    # distancia al centro del primer voxel vacío -> al borde real: restar medio pitch
    edt = np.where(occ, np.maximum(edt - pitch / 2, pitch / 2), 0.0)
    return VoxelField(origin=origin, pitch=pitch, occ=occ, edt=edt)


@dataclass
class CellGraph:
    centers: np.ndarray  # (n,3) centroides de celda, frame de la malla
    volume: np.ndarray  # mm3
    modulus: np.ndarray  # mm (máx EDT en la celda = núcleo)
    neck: sparse.csr_matrix  # peso = min(m_a, m_b) (0 = sin arista)
    length: sparse.csr_matrix  # distancia entre centroides
    cell_size: float
    keys: dict  # (i,j,k) -> índice
    mst: sparse.csr_matrix | None = None  # árbol de cuello máximo (cache)
    vox_pos: np.ndarray | None = None  # centros de voxel ocupados
    vox_cell: np.ndarray | None = None  # celda de cada voxel
    vox_edt: np.ndarray | None = None


def cell_graph(vf: VoxelField, cell: float = 0.75) -> CellGraph:
    idx = np.argwhere(vf.occ)
    pos = vf.centers(idx)
    ck = np.floor((pos - vf.origin) / cell).astype(np.int64)
    uniq, inv = np.unique(ck, axis=0, return_inverse=True)
    inv = inv.ravel()
    n = len(uniq)
    cnt = np.bincount(inv, minlength=n).astype(float)
    centers = np.zeros((n, 3))
    for d in range(3):
        centers[:, d] = np.bincount(inv, weights=pos[:, d], minlength=n) / cnt
    m = np.zeros(n)
    np.maximum.at(m, inv, vf.edt[tuple(idx.T)])
    keys = {tuple(k): i for i, k in enumerate(map(tuple, uniq))}

    # conectividad real: dos celdas vecinas se conectan si hay voxels ocupados adyacentes entre ellas
    dims = uniq.max(0) + 2
    code = lambda k: (k[:, 0] * dims[1] + k[:, 1]) * dims[2] + k[:, 2]  # noqa: E731
    ucode = code(uniq)
    order = np.argsort(ucode)
    rows, cols = [], []
    occ = vf.occ
    for off in [(1, 0, 0), (0, 1, 0), (0, 0, 1)]:
        a = occ[: occ.shape[0] - off[0], : occ.shape[1] - off[1], : occ.shape[2] - off[2]]
        b = occ[off[0]:, off[1]:, off[2]:]
        both = np.argwhere(a & b)
        if not len(both):
            continue
        ca = np.floor((vf.centers(both) - vf.origin) / cell).astype(np.int64)
        cb = np.floor((vf.centers(both + off) - vf.origin) / cell).astype(np.int64)
        diff = np.any(ca != cb, axis=1)
        for arr, dst in ((ca[diff], rows), (cb[diff], cols)):
            c = code(arr)
            dst.append(order[np.searchsorted(ucode, c, sorter=order)])
    rows = np.concatenate(rows) if rows else np.zeros(0, int)
    cols = np.concatenate(cols) if cols else np.zeros(0, int)
    pairs = np.unique(np.sort(np.c_[rows, cols], axis=1), axis=0) if len(rows) else np.zeros((0, 2), int)
    i, j = pairs[:, 0], pairs[:, 1]
    w_neck = np.minimum(m[i], m[j])
    w_len = np.linalg.norm(centers[i] - centers[j], axis=1) + 1e-9
    neck = sparse.coo_matrix((np.r_[w_neck, w_neck], (np.r_[i, j], np.r_[j, i])), shape=(n, n)).tocsr()
    length = sparse.coo_matrix((np.r_[w_len, w_len], (np.r_[i, j], np.r_[j, i])), shape=(n, n)).tocsr()
    return CellGraph(centers, cnt * vf.pitch**3, m, neck, length, cell, keys,
                     vox_pos=pos, vox_cell=inv, vox_edt=vf.edt[tuple(idx.T)])


def widest_path_from(g: CellGraph, source: int) -> np.ndarray:
    """Cuello máximo alcanzable (maximin) desde `source` a cada celda. -inf si no conectada.

    Árbol generador máximo (Kruskal) -> el cuello entre dos nodos es la arista mínima del camino en el árbol.
    """
    mst = _max_spanning_tree(g)
    n = len(g.modulus)
    out = np.full(n, -np.inf)
    out[source] = np.inf  # la fuente es el feeder: no limita el cuello
    order, pred = sparse.csgraph.breadth_first_order(mst, source, directed=False, return_predecessors=True)
    coo = mst.tocoo()
    w = {(int(a), int(b)): float(c) for a, b, c in zip(coo.row, coo.col, coo.data)}
    for v in order[1:]:
        u = pred[v]
        out[v] = min(out[u], w[(int(u), int(v))])
    return out


def _max_spanning_tree(g: CellGraph) -> sparse.csr_matrix:
    if g.mst is None:
        big = g.neck.max() + 1.0
        inv = g.neck.copy()
        inv.data = big - inv.data  # MST mínimo sobre (big - w) = árbol de cuello máximo
        t = sparse.csgraph.minimum_spanning_tree(inv).tocsr()
        t.data = big - t.data
        g.mst = (t + t.T).tocsr()
    return g.mst


def geodesic_from(g: CellGraph, sources) -> np.ndarray:
    """Distancia geodésica (a través del metal) desde cada fuente: shape (len(sources), n)."""
    return sparse.csgraph.dijkstra(g.length, directed=False, indices=np.atleast_1d(sources))


def nearest_cell(g: CellGraph, p) -> int:
    return int(np.argmin(np.linalg.norm(g.centers - np.asarray(p), axis=1)))


def cell_size_for(volume_mm3: float) -> float:
    """Tamaño de celda: ~0.75 mm, más grueso en piezas grandes (grafo < ~6000 celdas)."""
    return max(0.75, (volume_mm3 / 6000.0) ** (1 / 3))


def pitch_for(extent_mm: float) -> float:
    return max(0.12, min(0.25, extent_mm / 170.0)) if math.isfinite(extent_mm) else 0.15
