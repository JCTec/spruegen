"""Glue between the GUI and the spruegen pipeline. No geometry here: only calls + JSON shaping."""

from __future__ import annotations

import json
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from pydantic import ValidationError

from spruegen.plan import analysis
from spruegen import pipeline
from spruegen.detect import features
from spruegen.config import presets
from spruegen.schemas import FeatureError, Profile, SpruegenError
from spruegen.gui.i18n import translate, translate_all

ZONE_COLORS = ["#d9573b", "#3b7dd9", "#2e9e5b", "#b85fc9", "#e0a526", "#20a4b8"]
ADV_TOP = ("min_attach_thickness_mm", "feeder_d_min_mm", "feeder_d_max_mm")
ADV_TREE = ("feed_reach_mm", "feeder_capacity_mm3")
TREE_MODES = ("auto", "single", "spider", "y")


class GuiError(Exception):
    """Error with an English, user-facing message."""


@dataclass
class Session:
    sid: str
    dir: Path
    name: str
    stl: Path
    generation: int = 0
    result_ok: bool = False
    info: dict = field(default_factory=dict)


# ---------------------------------------------------------------- settings


def preset_list() -> list[dict]:
    out = []
    for name, p in presets.available().items():
        out.append({
            "name": name,
            "metal": p.metal,
            "process": p.process,
            "notes": p.notes or "",
            "advanced": advanced_of(p),
            "stem": {"d_mm": p.stem_d_mm, "h_mm": p.stem_h_mm},
            "stub": {"d_mm": p.stub_d_mm, "h_mm": p.stub_h_mm},
            "stem_kind": p.stem_kind,
        })
    return out


def advanced_of(p: Profile) -> dict:
    return {
        "min_attach_thickness_mm": p.min_attach_thickness_mm,
        "feeder_d_min_mm": p.feeder_d_min_mm,
        "feeder_d_max_mm": p.feeder_d_max_mm,
        "feed_reach_mm": p.tree.feed_reach_mm,
        "feeder_capacity_mm3": p.tree.feeder_capacity_mm3,
    }


def build_profile(config: dict, sdir: Path) -> Path:
    """Preset + advanced + stem edits -> <session>/profile.json.

    The stem the user picks here is a deliberate choice: it becomes the size that locks and validation check.
    """
    try:
        prof = presets.load(config.get("preset") or "ag925")
    except SpruegenError as e:
        raise GuiError(translate(str(e)))
    data = prof.model_dump()
    for k, v in (config.get("advanced") or {}).items():
        if v in (None, ""):
            continue
        if k in ADV_TOP:
            data[k] = float(v)
        elif k in ADV_TREE:
            data["tree"][k] = float(v)
    stem = config.get("stem") or {}
    if stem:
        kind = stem.get("kind") or "downstem"
        if kind not in ("downstem", "stub"):
            raise GuiError(f"Unknown stem option: {kind}")
        data["stem_kind"] = kind
        prefix = "stub" if kind == "stub" else "stem"
        for dim in ("d_mm", "h_mm"):
            if stem.get(dim) not in (None, ""):
                try:
                    data[f"{prefix}_{dim}"] = float(stem[dim])
                except (TypeError, ValueError):
                    raise GuiError(f"Invalid stem setting: {dim}={stem[dim]!r}")
    try:
        prof = Profile.model_validate(data)
    except ValidationError as e:
        msgs = "; ".join(translate(err["msg"].removeprefix("Value error, ")) for err in e.errors())
        raise GuiError(f"Invalid setting: {msgs}")
    path = sdir / "profile.json"
    path.write_text(prof.model_dump_json(indent=2))
    return path


def cli_flags(config: dict) -> tuple[str, int | None, str]:
    mode = config.get("tree_mode") or "auto"
    if mode not in TREE_MODES:
        raise GuiError(f"Unknown tree type: {mode}")
    feeders = config.get("feeders")
    feeders = int(feeders) if feeders and mode in ("spider", "y") else None
    vents = str(config.get("vents") or "off").lower()
    if vents not in ("off", "auto") and not vents.isdigit():
        raise GuiError(f"Unknown vents option: {vents}")
    return mode, feeders, vents


def _profile_for(config: dict, sdir: Path) -> tuple[Path, Profile]:
    path = build_profile(config, sdir)
    mode, feeders, vents = cli_flags(config)
    return path, pipeline.apply_cli(presets.load(path), mode, feeders, vents)


# ---------------------------------------------------------------- steps


def load_summary(stl: Path) -> dict:
    """Validate the ring (units, watertight, finger hole) and describe it."""
    try:
        mesh, rep = pipeline.load_ring(stl)
    except SpruegenError as e:
        raise GuiError(translate(str(e)))
    ext = mesh.extents
    summary = {
        "volume_mm3": float(mesh.volume),
        "size_mm": [float(x) for x in ext],
        "faces": int(len(mesh.faces)),
    }
    warnings = []
    if rep.get("normals_fixed"):
        warnings.append("the STL had inverted/odd normals (repaired)")
    try:
        f = features.detect(mesh, Profile(), max_candidates=1)
        summary.update(
            inner_d_mm=2 * f.inner_radius_mm,
            band_width_mm=f.band_width_mm,
            thickness_median_mm=f.scan.get("thickness_median_mm"),
            thickness_max_mm=f.inner_thickness_max_mm,
            head=f.head_detected,
        )
        warnings += translate_all(f.warnings)
    except FeatureError as e:
        msg = str(e)
        if "hueco del dedo" in msg:
            raise GuiError(translate(msg))
        warnings.append(translate(msg))
    return {"summary": summary, "warnings": warnings}


def analyze(sess: Session, config: dict) -> dict:
    _, prof = _profile_for(config, sess.dir)
    out = sess.dir / "analysis"
    if out.exists():
        shutil.rmtree(out)
    try:
        res = pipeline.run_analyze(sess.stl, None, out, prof=prof)
    except (SpruegenError, ValueError) as e:
        raise GuiError(translate(str(e)))
    s = res.summary
    zones = []
    for name in sorted(analysis.zone_meshes(res)):
        idx = -1 if name == "zone_isolated" else int(name.replace("zone_feeder", "")) - 1
        zones.append({
            "name": name,
            "label": "isolated (not fed)" if idx < 0 else f"zone of feeder {idx + 1}",
            "url": f"analysis/{name}.stl",
            "color": "#1d1d1f" if idx < 0 else ZONE_COLORS[idx % len(ZONE_COLORS)],
        })
    return {
        "feeder_count": s["feeder_count"],
        "coverage": s["coverage"],
        "reasons": translate_all(s["reasons"]),
        "warnings": translate_all(s["warnings"]),
        "feeders": [
            {"angle_deg": f["theta_deg"] % 360, "height_mm": f["h_mm"], "thickness_mm": f["thickness_mm"],
             "feeds_frac": f["feeds_volume_frac"], "head": f["head"]}
            for f in s["feeders"]
        ],
        "last_to_fill": [{"angle_deg": t["theta_deg"] % 360} for t in s["last_to_fill"][:3]],
        "hot_spot_max_mm": s["modulus_mm"]["max"],
        "seconds": s["seconds"],
        "map_url": "analysis/analysis.png" if (out / "analysis.png").exists() else None,
        "zones": zones,
    }


def checklist(rep: dict, prop) -> list[dict]:
    m = rep.get("metrics", {})
    st = m.get("stem", {})
    p = prop.profile
    errs = " ".join(rep.get("errors", []))
    d, h = st.get("d_mm"), st.get("h_mm")
    name = "Stub" if prop.stem.kind == "stub" else "Stem"
    stem_bad = any(e.startswith((f"{name.lower()} mide", "no se pudo medir")) for e in rep.get("errors", []))
    outer = m.get("outer_surface_max_diff_mm")
    hole = m.get("hole_blocked_frac")
    piece = m.get("piece_height_mm")
    return [
        {"label": "Watertight (closed, printable surface)", "ok": bool(m.get("watertight")), "detail": ""},
        {"label": "One piece (every sprue attached)", "ok": m.get("bodies") == 1,
         "detail": f"{m.get('bodies', '?')} piece(s)"},
        {"label": f"{name} Ø{prop.stem.d_mm:g} × {prop.stem.h_mm:g} mm",
         "ok": bool(st.get("ok")) and not stem_bad,
         "detail": f"measured Ø{d:.2f} × {h:.2f} mm" if st.get("ok") else "not measured"},
        {"label": "Outer surface untouched", "ok": outer is not None and outer <= 0.05,
         "detail": f"max change {outer:.4f} mm" if outer is not None else ""},
        {"label": "Finger hole clear", "ok": hole is not None and hole <= p.hole_block_max_frac,
         "detail": f"{hole:.1%} blocked" if hole is not None else ""},
        {"label": "Feeders attach from the inside", "ok": "attach más cerca" not in errs and "no hay shank" not in errs,
         "detail": f"{len(prop.feeders)} feeder(s)"},
        {"label": "Fits the flask space", "ok": piece is not None and piece <= p.ring_space_mm,
         "detail": f"{piece:.1f} of {p.ring_space_mm:g} mm above the {name.lower()}" if piece is not None else ""},
        {"label": "Locked settings respected", "ok": "locks violados" not in errs,
         "detail": f"{name.lower()} Ø/height as chosen, inner attach"},
    ]


def generate(sess: Session, config: dict) -> dict:
    prof_path, _ = _profile_for(config, sess.dir)
    mode, feeders, vents = cli_flags(config)
    gen = sess.dir / "gen"
    if gen.exists():
        shutil.rmtree(gen)
    sess.result_ok = False
    try:
        prop = pipeline.run_propose(sess.stl, prof_path, None, gen, mode, feeders, vents)
        rep = pipeline.run_apply(gen / "proposal.json", gen / "out.stl")
    except (SpruegenError, ValueError) as e:
        raise GuiError(translate(str(e)))
    (gen / "validate.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False, default=float))
    sess.generation += 1
    sess.result_ok = bool(rep["ok"])
    meshes = {"ring": "gen/preview_ring.stl", "tree": "gen/preview_sprues.stl"}
    if prop.vents:
        meshes["vents"] = "gen/preview_vents.stl"
    if rep["ok"]:
        meshes["final"] = "gen/out.stl"
    used = prop.tree.get("used", mode)
    return {
        "generation": sess.generation,
        "ok": bool(rep["ok"]),
        "tree": {"requested": mode, "used": used, "label": tree_label(used)},
        "feeders": [
            {"d_mm": f.d_mm, "len_mm": f.len_mm, "angle_deg": f.angle_deg,
             "kind": "Y arm" if f.node_kind == "branch" else "direct"}
            for f in prop.feeders
        ],
        "branches": [{"d_mm": b.d_mm, "arms": [i + 1 for i in b.arms]} for b in prop.branches],
        "vents": [{"d_mm": v.d_mm, "len_mm": float(np.linalg.norm(np.subtract(v.top, v.base)))} for v in prop.vents],
        "stem": {"d_mm": prop.stem.d_mm, "h_mm": prop.stem.h_mm, "kind": prop.stem.kind},
        "reasons": translate_all(prop.tree.get("reasons", [])),
        "warnings": translate_all(prop.warnings) + translate_all(rep.get("warnings", [])),
        "validation": {"ok": bool(rep["ok"]), "checks": checklist(rep, prop), "errors": translate_all(rep["errors"])},
        "transform": prop.transform,
        "meshes": meshes,
        "piece_height_mm": prop.ring_job["piece_height_mm"],
        "casting": prop.casting,
    }


def tree_label(used: str) -> str:
    if used.startswith("auto:"):
        parts = used[5:].split("+")
        return "Auto — " + ", ".join("Y branch" if x == "y" else "direct" for x in parts)
    return {"single": "Single feeder", "spider": "Spider", "y": "Y branch"}.get(used, used)


def export_zip(sess: Session) -> Path:
    gen = sess.dir / "gen"
    if not sess.result_ok or not (gen / "out.stl").exists():
        raise GuiError("Nothing to export yet — generate a valid result first.")
    from spruegen.schemas import load_proposal

    prop = load_proposal(gen / "proposal.json")
    try:
        from spruegen.report import render

        if not (gen / "render.png").exists():
            render.render_proposal(prop, gen / "render.png", title=sess.name)
        imgs = ["render.png"]
        amap = sess.dir / "analysis" / "analysis.png"
        if amap.exists():
            shutil.copy(amap, gen / "analysis.png")
            imgs.append("analysis.png")
        rep = json.loads((gen / "validate.json").read_text())
        render.card_html(prop, imgs, rep, gen / "card.html", title=sess.name)
    except ImportError:
        pass
    stem = Path(sess.name).stem
    zpath = sess.dir / f"{stem}_sprued.zip"
    names = {"out.stl": f"{stem}_sprued.stl", "preview_ring.stl": None, "preview_sprues.stl": None,
             "preview_vents.stl": None, "proposal.json": None, "validate.json": None, "render.png": None,
             "analysis.png": None, "card.html": None}
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for src, arc in names.items():
            f = gen / src
            if f.exists():
                z.write(f, f"{stem}/{arc or src}")
    return zpath
