"""Imágenes para revisar y compartir: vistas 3D por pieza, mapa desenrollado del análisis, tarjeta HTML.

Requiere el extra `render` (matplotlib + fast_simplification).
"""

from __future__ import annotations

import html
import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import trimesh  # noqa: E402
from matplotlib.colors import ListedColormap, to_rgb  # noqa: E402
from mpl_toolkits.mplot3d.art3d import Poly3DCollection  # noqa: E402

from spruegen.construct import sprues as build
from spruegen.mesh import io
from spruegen.schemas import Proposal, load_proposal  # noqa: E402

COLORS = {"ring": "#b9bcc2", "sprue": "#d9573b", "vent": "#3b7dd9", "single": "#c8894f"}
LIGHT = np.array([0.35, -0.55, 0.75]) / np.linalg.norm([0.35, -0.55, 0.75])
MAX_FACES = 14000
ZONE_COLORS = ["#d9573b", "#3b7dd9", "#2e9e5b", "#b85fc9", "#e0a526", "#20a4b8"]


def _decimate(m: trimesh.Trimesh, n: int) -> trimesh.Trimesh:
    if len(m.faces) <= n:
        return m
    try:
        return m.simplify_quadric_decimation(face_count=n)
    except Exception:
        return m


def render_meshes(parts: list[tuple[trimesh.Trimesh, str]], out_png: Path, title: str = "",
                  views=((12, -35), (12, -100), (60, -100))) -> Path:
    """Una sola colección de polígonos (orden de profundidad correcto entre piezas)."""
    total = sum(len(m.faces) for m, _ in parts)
    tris, cols = [], []
    for m, col in parts:
        share = max(400, int(MAX_FACES * len(m.faces) / max(total, 1)))
        d = _decimate(m, share)
        shade = 0.32 + 0.68 * np.clip(d.face_normals @ LIGHT, 0, 1)
        tris.append(d.vertices[d.faces])
        cols.append(np.array(to_rgb(col))[None] * shade[:, None])
    tris = np.concatenate(tris)
    cols = np.concatenate(cols)
    allv = tris.reshape(-1, 3)
    lo, hi = allv.min(0), allv.max(0)
    fig = plt.figure(figsize=(5 * len(views), 5.4))
    for k, (el, az) in enumerate(views):
        ax = fig.add_subplot(1, len(views), k + 1, projection="3d")
        ax.add_collection3d(Poly3DCollection(tris, facecolors=cols, edgecolor="none"))
        # encuadre: vista 1 completa; vistas 2-3 enfocadas en el anillo (parte alta)
        if k == 0:
            c, h = (lo + hi) / 2, float((hi - lo).max()) / 2
        else:
            top = allv[allv[:, 2] > hi[2] - min(22.0, hi[2] - lo[2])]
            c, h = (top.min(0) + top.max(0)) / 2, float((top.max(0) - top.min(0)).max()) / 2 * 1.05
        ax.set_xlim(c[0] - h, c[0] + h)
        ax.set_ylim(c[1] - h, c[1] + h)
        ax.set_zlim(c[2] - h, c[2] + h)
        ax.set_box_aspect((1, 1, 1))
        ax.view_init(el, az)
        ax.set_axis_off()
    if title:
        fig.suptitle(title, fontsize=13)
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=90, facecolor="white")
    plt.close(fig)
    return out_png


def render_proposal(prop: Proposal, out_png: Path, title: str = "") -> Path:
    from spruegen.construct.validate import load_ring_job

    ring = load_ring_job(prop)
    tree_parts = build.build_sprues(prop.stem, prop.feeders, prop.fillets, prop.branches, None, prop.hub)
    parts = [(ring, COLORS["ring"])] + [(m, COLORS["sprue"]) for m in tree_parts]
    parts += [(m, COLORS["vent"]) for m in build.build_vents(prop.vents)]
    return render_meshes(parts, out_png, title)


def _unrolled(res, feats, values, reduce="max", dth=1.0):
    """Proyecta voxels a una grilla (ángulo x altura): imagen del anillo 'desenrollado'."""
    g = res.graph
    axis = np.array(feats.axis)
    c = np.array(feats.center)
    from spruegen.detect.features import plane_basis

    u, v = plane_basis(axis)
    q = g.vox_pos - c
    h = q @ axis
    th = np.degrees(np.arctan2(q @ v, q @ u)) % 360
    dh = res.field.pitch
    hmin, hmax = h.min(), h.max()
    ni, nj = int(math.ceil((hmax - hmin) / dh)) + 1, int(360 / dth)
    I = np.clip(np.round((h - hmin) / dh).astype(int), 0, ni - 1)
    J = np.clip((th / dth).astype(int), 0, nj - 1)
    img = np.full((ni, nj), np.nan)
    flat = I * nj + J
    if reduce == "max":
        buf = np.full(ni * nj, -np.inf)
        np.maximum.at(buf, flat, values)
    else:  # moda aproximada: el último escrito (valores enteros)
        buf = np.full(ni * nj, np.nan)
        buf[flat] = values
    buf[~np.isfinite(buf)] = np.nan
    img = buf.reshape(ni, nj)
    return img, (0, 360, hmin, hmax)


def analysis_png(res, feats, out_png: Path, title: str = "") -> Path:
    """Mapa desenrollado del anillo (ángulo x altura): espesor/módulo y zona de cada feeder."""
    g = res.graph
    fig, axs = plt.subplots(1, 2, figsize=(13, 3.9), sharey=True)
    img, ext = _unrolled(res, feats, g.vox_edt * 2, "max")  # 2*EDT máx a lo largo del radio ≈ espesor
    im = axs[0].imshow(img, origin="lower", aspect="auto", extent=ext, cmap="inferno", interpolation="nearest")
    fig.colorbar(im, ax=axs[0], label="espesor local ≈ 2×módulo (mm)")
    axs[0].set_title("Espesor / módulo térmico (claro = hot spot)")
    lab = res.fed_by[g.vox_cell].astype(float)
    zimg, _ = _unrolled(res, feats, lab + 1, "last")
    cmap = ListedColormap(["#222222"] + ZONE_COLORS)
    axs[1].imshow(zimg, origin="lower", aspect="auto", extent=ext, cmap=cmap, vmin=-0.5,
                  vmax=len(ZONE_COLORS) + 0.5, interpolation="nearest")
    axs[1].set_title("Zona que alimenta cada feeder (negro = aislada)")
    for ax in axs:
        for k, a in enumerate(res.attaches):
            ax.scatter([a.theta_deg % 360], [a.h_mm], marker="v", s=150, c=ZONE_COLORS[k % len(ZONE_COLORS)],
                       edgecolors="white", linewidths=1.5, zorder=5)
            ax.annotate(f"F{k + 1}", (a.theta_deg % 360, a.h_mm), textcoords="offset points", xytext=(7, 5),
                        color="white", fontsize=9, weight="bold")
        for vt in res.vent_targets[:2]:
            ax.scatter([vt["theta_deg"] % 360], [vt["h_mm"]], marker="*", s=180, c="#6fb0ff",
                       edgecolors="white", linewidths=1, zorder=5)
        ax.set_xlim(0, 360)
        ax.set_xlabel("ángulo alrededor del dedo (°)")
    axs[0].set_ylabel("altura en la banda (mm)")
    s = res.summary
    fig.suptitle(
        f"{title}  —  {s['feeder_count']} feeder(s), cobertura {s['coverage']:.0%}   "
        "(▼ feeder, ★ llega último → varilla)",
        fontsize=11,
    )
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=90, facecolor="white")
    plt.close(fig)
    return out_png


def _fmt(x, nd=2):
    return f"{x:.{nd}f}" if isinstance(x, (int, float)) else html.escape(str(x))


def card_html(prop: Proposal, images: list[str], report: dict | None, out_html: Path, title: str = "") -> Path:
    rows = [
        ("Anillo", Path(prop.input["path"]).name),
        ("Volumen", f"{prop.input['volume_mm3']:.0f} mm³"),
        ("Metal / proceso", f"{prop.profile.metal} / {prop.profile.process}"),
        ("Árbol", f"{prop.tree.get('used', 'single')} — {len(prop.feeders)} feeder(s), {len(prop.vents)} varilla(s)"),
        ("Feeders", ", ".join(f"Ø{f.d_mm:.2f}×{f.len_mm:.1f} mm @{f.angle_deg:.0f}°" for f in prop.feeders)),
        (prop.stem.kind.capitalize(), f"Ø{prop.stem.d_mm} × {prop.stem.h_mm} mm"),
        (f"Pieza sobre el {'stub' if prop.stem.kind == 'stub' else 'stem'}",
         f"{prop.ring_job['piece_height_mm']:.1f} / {prop.profile.ring_space_mm:g} mm"),
    ]
    if prop.branches:
        rows.append(("Troncos (Y)", ", ".join(f"Ø{b.d_mm:.2f} mm" for b in prop.branches)))
    if prop.analysis:
        rows.append(("Cobertura (análisis)", f"{prop.analysis['coverage']:.0%}"))
    if report:
        mt = report.get("metrics", {})
        rows += [
            ("Validación", "OK" if report.get("ok") else "FALLA: " + "; ".join(report.get("errors", []))),
            ("Cara externa", f"cambio máx. {mt.get('outer_surface_max_diff_mm', float('nan')):.4f} mm"),
            ("Hueco del dedo", f"{mt.get('hole_blocked_frac', 0):.1%} bloqueado"),
        ]
    reasons = prop.tree.get("reasons", [])
    body = [
        "<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'>",
        f"<title>{html.escape(title or Path(prop.input['path']).stem)}</title>",
        "<style>body{font-family:system-ui,sans-serif;max-width:1100px;margin:24px auto;padding:0 16px;color:#222}"
        "img{max-width:100%;border:1px solid #ddd;border-radius:6px;margin:6px 0}"
        "table{border-collapse:collapse}td{padding:4px 12px;border-bottom:1px solid #eee;vertical-align:top}"
        "td:first-child{color:#666}.w{color:#9a5b00}</style></head><body>",
        f"<h2>{html.escape(title or Path(prop.input['path']).stem)}</h2>",
    ]
    body += [f"<img src='{html.escape(i)}'>" for i in images]
    body.append("<table>" + "".join(f"<tr><td>{html.escape(k)}</td><td>{html.escape(str(v))}</td></tr>"
                                    for k, v in rows) + "</table>")
    if reasons:
        body.append("<h4>Por qué este árbol</h4><ul>" + "".join(f"<li>{html.escape(r)}</li>" for r in reasons)
                    + "</ul>")
    if prop.warnings:
        body.append("<h4>Avisos</h4><ul class='w'>" + "".join(f"<li>{html.escape(w)}</li>" for w in prop.warnings)
                    + "</ul>")
    body.append("</body></html>")
    out_html.write_text("\n".join(body))
    return out_html


def render_target(target: Path, out: Path | None = None) -> list[Path]:
    target = Path(target)
    if target.suffix == ".json":
        prop = load_proposal(target)
        png = out or target.with_name("render.png")
        render_proposal(prop, png, Path(prop.input["path"]).stem)
        rep_path = target.with_name("validate.json")
        report = json.loads(rep_path.read_text()) if rep_path.exists() else None
        imgs = [png.name] + [n for n in ("analysis.png",) if (target.parent / n).exists()]
        card = card_html(prop, imgs, report, target.with_name("card.html"))
        return [png, card]
    mesh = io.load_stl(target)
    mesh.merge_vertices()
    png = out or target.with_suffix(".png")
    return [render_meshes([(mesh, COLORS["single"])], png, target.stem)]

