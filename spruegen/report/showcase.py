"""Anillos de ejemplo paramétricos + `spruegen demo`: pipeline completo y galería HTML.

Todos en mm, eje del dedo = Z, construidos con booleanos manifold (watertight).
"""

from __future__ import annotations

import html
import json
import math
import time
import traceback
from pathlib import Path

import numpy as np
import trimesh

from spruegen.mesh import io

# ---------------------------------------------------------------- utilidades


def _mf(meshes, op="union") -> trimesh.Trimesh:
    fn = {"union": trimesh.boolean.union, "difference": trimesh.boolean.difference,
          "intersection": trimesh.boolean.intersection}[op]
    return fn(meshes, engine="manifold")


def revolve_profile(pts_rz: list[tuple[float, float]], sections: int = 160) -> trimesh.Trimesh:
    """Revoluciona un perfil cerrado (r, z) alrededor de Z."""
    pts = np.asarray(pts_rz, float)
    if np.allclose(pts[0], pts[-1]):
        pts = pts[:-1]
    m = trimesh.creation.revolve(np.vstack([pts, pts[:1]]), sections=sections)
    m.merge_vertices()
    trimesh.repair.fix_normals(m)
    if m.volume < 0:
        m.invert()
    return m


def band(inner_r: float, width: float, thick: float, comfort: float = 0.3, dome: float = 0.25,
         n: int = 24) -> trimesh.Trimesh:
    """Banda: cara interna comfort-fit (convexa hacia el dedo), exterior levemente abombado."""
    zs = np.linspace(-width / 2, width / 2, n)
    s = (2 * zs / width) ** 2
    r_in = inner_r + comfort * s
    r_out = inner_r + thick - dome * s
    outer = list(zip(r_out, zs))
    inner = list(zip(r_in[::-1], zs[::-1]))
    return revolve_profile(outer + inner)


# ---------------------------------------------------------------- anillos


def plain_band() -> trimesh.Trimesh:
    """Alianza comfort-fit 4 mm x 1.8 mm, ID 18 mm."""
    return band(9.0, 4.0, 1.8)


def wide_band() -> trimesh.Trimesh:
    """Banda ancha y pesada: 8 mm x 2.2 mm, ID 18.5 mm (~1150 mm³)."""
    return band(9.25, 8.0, 2.2, comfort=0.35, dome=0.3, n=32)


def lattice_band() -> trimesh.Trimesh:
    """Banda 6 x 2 mm con ventanas pasantes en rombo (dos filas alternadas) y cantos sólidos."""
    ring = band(9.5, 6.0, 2.0, comfort=0.2, dome=0.2, n=28)
    cutters = []
    for row, (z, off) in enumerate(((1.15, 0.0), (-1.15, 360.0 / 32))):
        for k in range(16):
            ang = math.radians(k * 360.0 / 16 + off)
            box = trimesh.creation.box(extents=[1.45, 1.45, 8.0])  # largo en z -> se orienta radial
            box.apply_transform(trimesh.transformations.rotation_matrix(math.pi / 4, [0, 0, 1]))
            # eje largo (z) -> radial (x), rombo en el plano (tangencial, axial)
            box.apply_transform(trimesh.transformations.rotation_matrix(math.pi / 2, [0, 1, 0]))
            box.apply_translation([10.5, 0.0, z])
            box.apply_transform(trimesh.transformations.rotation_matrix(ang, [0, 0, 1]))
            cutters.append(box)
    return _mf([ring, _mf(cutters)], "difference")


def signet() -> trimesh.Trimesh:
    """Sello: shank 3 x 1.8 mm + cabeza ovalada maciza (14 x 12 mm) en +X. Hot spot aislado."""
    shank = band(9.0, 3.0, 1.8, comfort=0.15, dome=0.2)
    oval = trimesh.creation.cylinder(radius=1.0, height=5.2, sections=96)
    oval.apply_scale([6.0, 7.0, 1.0])  # elipse: 12 (y) x 14 (z)
    oval.apply_transform(trimesh.transformations.rotation_matrix(math.pi / 2, [0, 1, 0]))  # eje -> X
    oval.apply_translation([11.3, 0.0, 0.0])
    hole = trimesh.creation.cylinder(radius=9.02, height=30.0, sections=160)
    head = _mf([oval, hole], "difference")
    # afinar los costados de la cabeza hacia el shank (no un bloque)
    taper = trimesh.creation.icosphere(subdivisions=4, radius=13.9)
    taper.apply_translation([-0.6, 0.0, 0.0])
    head = _mf([head, taper], "intersection")
    return _mf([shank, head])


def solitaire() -> trimesh.Trimesh:
    """Solitario: shank fino 2 x 1.7 mm + canasta de 4 garras con galería en +X."""
    shank = band(8.75, 2.2, 1.7, comfort=0.15, dome=0.25)
    parts = [shank]
    for sy in (-1, 1):
        for sz in (-1, 1):
            a = np.array([10.1, 0.75 * sy, 0.75 * sz])
            b = np.array([15.0, 1.9 * sy, 1.9 * sz])
            parts.append(trimesh.creation.cylinder(radius=0.45, segment=np.array([a, b]), sections=16))
            tip = trimesh.creation.icosphere(subdivisions=2, radius=0.5)
            tip.apply_translation(b)
            parts.append(tip)
    gallery = trimesh.creation.torus(major_radius=1.55, minor_radius=0.35, major_sections=48, minor_sections=12)
    gallery.apply_transform(trimesh.transformations.rotation_matrix(math.pi / 2, [0, 1, 0]))
    gallery.apply_translation([12.6, 0.0, 0.0])
    parts.append(gallery)
    return _mf(parts)


def carved_band() -> trimesh.Trimesh:
    """Interior liso, exterior delgado (1 mm) + un sector tallado grueso hacia -Y."""
    b = trimesh.creation.annulus(r_min=9.5, r_max=10.5, height=4.0, sections=128)
    pad = trimesh.creation.box(extents=[6.0, 2.4, 4.0])
    pad.apply_translation([0.0, -11.2, 0.0])
    return _mf([b, pad])


def dumbbell_ring() -> trimesh.Trimesh:
    """Dos masas gruesas (±X) unidas por un shank fino: dos hot spots aislados -> dos feeders."""
    shank = band(9.5, 2.0, 1.4, comfort=0.1, dome=0.1)
    hole = trimesh.creation.cylinder(radius=9.52, height=30.0, sections=160)
    blobs = []
    for sx in (-1, 1):
        s = trimesh.creation.icosphere(subdivisions=4, radius=2.6)
        s.apply_scale([1.0, 1.3, 1.0])
        s.apply_translation([sx * 11.2, 0.0, 0.0])
        blobs.append(s)
    return _mf([shank, _mf([_mf(blobs), hole], "difference")])


RINGS = {
    "plain_band": plain_band,
    "wide_band": wide_band,
    "lattice_band": lattice_band,
    "signet": signet,
    "solitaire": solitaire,
    "carved_band": carved_band,
}

# (nombre del caso, anillo, flags de propose, qué muestra)
CASES = [
    ("plain_band", "plain_band", {}, "Alianza lisa: el análisis pide 1 feeder."),
    ("plain_band_y", "plain_band", {"tree_mode": "y", "feeders": 2}, "Misma alianza con árbol en Y (2 brazos, 1 tronco)."),
    ("wide_band", "wide_band", {"vents_opt": "auto"},
     "Banda ancha y pesada: la capacidad pide 2 feeders simétricos + varillas donde llega último."),
    ("wide_band_spider3", "wide_band", {"tree_mode": "spider", "feeders": 3}, "Spider de 3 feeders iguales a 120°."),
    ("lattice_band", "lattice_band", {"vents_opt": "2"},
     "Ventanas pasantes: el attach evita las ventanas (veto de lattice) y usa los cantos sólidos."),
    ("signet", "signet", {}, "Sello: la cabeza es un hot spot aislado → feeder por dentro, bajo la cabeza."),
    ("solitaire", "solitaire", {"vents_opt": "2"},
     "Solitario: las garras son finas (no son hot spot) → feeder en el shank, lejos del setting."),
    ("carved_band", "carved_band", {}, "Exterior tallado: el attach cae en el sector grueso, siempre por dentro."),
]
USER_CASES = [
    ("single", {"tree_mode": "single"}, "Tu anillo, un solo feeder (v0.1)."),
    ("auto_vents", {"tree_mode": "auto", "vents_opt": "auto"}, "Tu anillo en automático + varillas."),
    ("y", {"tree_mode": "y", "feeders": 2}, "Tu anillo con árbol en Y."),
    ("spider2", {"tree_mode": "spider", "feeders": 2}, "Tu anillo con 2 feeders directos."),
]


# ---------------------------------------------------------------- demo


def _run_case(name, stl: Path, flags: dict, desc: str, root: Path, echo) -> dict:
    from spruegen import pipeline
    from spruegen.report import render

    wd = root / name
    wd.mkdir(parents=True, exist_ok=True)
    row = {"name": name, "desc": desc, "ok": False, "error": ""}
    t0 = time.time()
    try:
        prof = pipeline.apply_cli(pipeline.load_profile(None), flags.get("tree_mode"), flags.get("feeders"),
                             flags.get("vents_opt"))
        res = pipeline.run_analyze(stl, None, None, prof=prof)
        (wd / "analysis.json").write_text(json.dumps(res.summary, indent=2, ensure_ascii=False))
        from spruegen.detect import features

        mesh, _ = pipeline.load_ring(stl)
        feats = features.detect(mesh, prof, None, max_candidates=10, respect_head=False)
        render.analysis_png(res, feats, wd / "analysis.png", title=name)
        prop = pipeline.run_propose(stl, None, None, wd, flags.get("tree_mode"), flags.get("feeders"),
                               flags.get("vents_opt"))
        rep = pipeline.run_apply(wd / "proposal.json", wd / "out.stl")
        (wd / "validate.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False, default=float))
        render.render_proposal(prop, wd / "render.png", title=name)
        render.card_html(prop, ["render.png", "analysis.png"], rep, wd / "card.html", title=name)
        mt = rep["metrics"]
        row.update(
            ok=bool(rep["ok"]),
            error="; ".join(rep["errors"]),
            tree=prop.tree["used"],
            feeders=len(prop.feeders),
            feeder_d=", ".join(f"{f.d_mm:.2f}" for f in prop.feeders),
            vents=len(prop.vents),
            coverage=res.summary["coverage"],
            volume=prop.input["volume_mm3"],
            piece_h=prop.ring_job["piece_height_mm"],
            outer_diff=mt.get("outer_surface_max_diff_mm"),
            hole=mt.get("hole_blocked_frac"),
            reasons=prop.tree.get("reasons", []),
            warnings=prop.warnings,
        )
    except Exception as e:  # la galería registra el fallo y sigue
        row["error"] = f"{type(e).__name__}: {e}"
        (wd / "error.txt").write_text(traceback.format_exc())
    row["seconds"] = round(time.time() - t0, 1)
    echo(f"{'OK ' if row['ok'] else 'ERR'} {name:24s} {row.get('feeders', '-')} feeder(s) "
         f"{row.get('tree', '')} {row['seconds']} s {row['error']}")
    return row


def run_demo(out_dir: Path, extra_ring: Path | None = None, echo=print) -> bool:
    out_dir = Path(out_dir)
    rings_dir = out_dir / "rings"
    rings_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    from spruegen.mesh.union import stl_safe

    for name, fn in RINGS.items():
        io.save_stl_atomic(stl_safe(fn()), rings_dir / f"{name}.stl")
    for name, ring, flags, desc in CASES:
        rows.append(_run_case(name, rings_dir / f"{ring}.stl", flags, desc, out_dir, echo))
    if extra_ring is not None and Path(extra_ring).exists():
        stem = Path(extra_ring).stem
        for suffix, flags, desc in USER_CASES:
            rows.append(_run_case(f"{stem}_{suffix}", Path(extra_ring), flags, desc, out_dir, echo))
    write_gallery(rows, out_dir)
    return all(r["ok"] for r in rows)


def write_gallery(rows: list[dict], out_dir: Path) -> None:
    cards = []
    for r in rows:
        n = html.escape(r["name"])
        if r["ok"]:
            stats = (
                f"<b>{r['feeders']}</b> feeder(s) · {html.escape(r['tree'])} · Ø {html.escape(r['feeder_d'])} mm · "
                f"{r['vents']} varilla(s)<br>cobertura {r['coverage']:.0%} · {r['volume']:.0f} mm³ · "
                f"pieza {r['piece_h']:.1f} mm · cara externa Δ {r['outer_diff']:.4f} mm · "
                f"hueco {r['hole']:.1%}"
            )
            why = "".join(f"<li>{html.escape(x)}</li>" for x in r.get("reasons", []))
            warn = "".join(f"<li>{html.escape(x)}</li>" for x in r.get("warnings", []))
            body = (
                f"<a href='{n}/card.html'><img src='{n}/render.png' loading='lazy'></a>"
                f"<img src='{n}/analysis.png' loading='lazy'>"
                f"<p>{stats}</p><ul class='why'>{why}</ul>" + (f"<ul class='w'>{warn}</ul>" if warn else "")
                + f"<p class='files'><a href='{n}/out.stl'>out.stl</a> · <a href='{n}/proposal.json'>proposal.json</a>"
                f" · <a href='{n}/preview_ring.stl'>preview_ring</a> · <a href='{n}/preview_sprues.stl'>preview_sprues</a>"
                "</p>"
            )
        else:
            body = f"<p class='err'>FALLÓ: {html.escape(r['error'])}</p>"
        cards.append(f"<section><h2>{n} <span class='{'ok' if r['ok'] else 'bad'}'>"
                     f"{'✓' if r['ok'] else '✗'}</span></h2><p class='d'>{html.escape(r['desc'])}</p>{body}</section>")
    page = f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>spruegen · galería</title>
<style>
:root{{--bg:#fafaf8;--fg:#1d1d1f;--mut:#6b6b70;--card:#fff;--line:#e4e4e0;--ok:#2e9e5b;--bad:#c9352b;--w:#9a5b00}}
@media (prefers-color-scheme: dark){{:root{{--bg:#151517;--fg:#ececef;--mut:#a0a0a8;--card:#1f1f23;--line:#333338;--w:#e0a526}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;max-width:1200px;margin:0 auto;padding:24px 16px}}
h1{{margin:0 0 4px}} .lead{{color:var(--mut);margin:0 0 24px}}
section{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin:0 0 20px}}
h2{{margin:0;font-size:18px}} .d{{color:var(--mut);margin:2px 0 8px}}
img{{width:100%;border-radius:6px;background:#fff;margin:4px 0}}
.ok{{color:var(--ok)}} .bad{{color:var(--bad)}} .err{{color:var(--bad)}} .w{{color:var(--w)}}
.why{{margin:4px 0}} .files a{{color:inherit}}
</style></head><body>
<h1>spruegen · galería</h1>
<p class="lead">Árboles de colada generados automáticamente: feeders solo por la cara interna, stem Ø10×35 mm,
cara externa intacta (Δ = cambio máximo medido). Mapas: anillo "desenrollado" (ángulo × altura);
▼ feeder, ★ donde el metal llega último.</p>
{''.join(cards)}
</body></html>"""
    (out_dir / "index.html").write_text(page)
    lines = ["# spruegen · showcase", "",
             "| caso | ok | árbol | feeders | Ø feeder (mm) | varillas | cobertura | volumen mm³ | Δ cara ext. mm |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if r["ok"]:
            lines.append(f"| {r['name']} | ✓ | {r['tree']} | {r['feeders']} | {r['feeder_d']} | {r['vents']} | "
                         f"{r['coverage']:.0%} | {r['volume']:.0f} | {r['outer_diff']:.4f} |")
        else:
            lines.append(f"| {r['name']} | ✗ | | | | | | | {r['error'][:80]} |")
    lines += ["", "Cada carpeta: `render.png`, `analysis.png`, `card.html`, `proposal.json`, previews y `out.stl`."]
    (out_dir / "README.md").write_text("\n".join(lines) + "\n")
