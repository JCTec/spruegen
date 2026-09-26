"""Construye las mallas separadas (stem, feeders, troncos, nudos, varillas) y exporta previews sin unir."""

from __future__ import annotations

from pathlib import Path

import manifold3d
import numpy as np
import trimesh

from . import io
from .schemas import Branch, Feeder, Hub, Sphere, Stem, Vent

STEM_SECTIONS = 48
FEEDER_SECTIONS = 32
VENT_SECTIONS = 24
SPHERE_SUBDIV = 3
CLIP_SECTIONS = 256


def build_stem(stem: Stem) -> trimesh.Trimesh:
    m = trimesh.creation.cylinder(radius=stem.d_mm / 2, height=stem.h_mm, sections=STEM_SECTIONS)
    m.apply_translation(np.array(stem.origin) + [0.0, 0.0, stem.h_mm / 2])  # base en z=0
    return m


def build_feeder(feeder: Feeder) -> trimesh.Trimesh:
    return trimesh.creation.cylinder(
        radius=feeder.d_mm / 2, segment=np.array([feeder.start, feeder.end]), sections=FEEDER_SECTIONS
    )


def build_fillet(s: Sphere) -> trimesh.Trimesh:
    m = trimesh.creation.icosphere(subdivisions=SPHERE_SUBDIV, radius=s.r_mm)
    m.apply_translation(s.center)
    return m


def _clip_cylinder(r: float, z0: float, z1: float) -> trimesh.Trimesh:
    clip = trimesh.creation.cylinder(radius=r, height=z1 - z0, sections=CLIP_SECTIONS)
    clip.apply_translation([0.0, 0.0, (z0 + z1) / 2])
    return clip


def _clip_to_radius(parts: list[trimesh.Trimesh], r: float) -> trimesh.Trimesh:
    top = max(float(m.bounds[1, 2]) for m in parts) + 1.0
    bot = min(float(m.bounds[0, 2]) for m in parts) - 1.0
    joined = trimesh.boolean.union(parts, engine="manifold") if len(parts) > 1 else parts[0]
    return trimesh.boolean.intersection([joined, _clip_cylinder(r, bot, top)], engine="manifold")


def build_ring_join(feeder: Feeder, fillets: list[Sphere] | None = None) -> trimesh.Trimesh:
    """Feeder + filete del lado del anillo, recortados por el cilindro r=clip_r (penetración acotada)."""
    parts = [build_feeder(feeder)]
    if feeder.ring_fillet is not None:
        parts.append(build_fillet(feeder.ring_fillet))
    elif fillets:  # compatibilidad: filete del anillo en la lista global
        parts += [build_fillet(s) for s in fillets if s.role == "ring_join"]
    return _clip_to_radius(parts, feeder.clip_r_mm)


def build_branch(b: Branch) -> trimesh.Trimesh:
    return trimesh.creation.cylinder(radius=b.d_mm / 2, segment=np.array([b.start, b.end]), sections=FEEDER_SECTIONS)


def build_vent(v: Vent) -> trimesh.Trimesh:
    rod = trimesh.creation.cylinder(radius=v.d_mm / 2, segment=np.array([v.base, v.top]), sections=VENT_SECTIONS)
    return _clip_to_radius([rod], v.clip_r_mm)


def build_hub(h: Hub) -> trimesh.Trimesh:
    man = manifold3d.Manifold.cylinder(h.z1 - h.z0, h.r0, h.r1, 64).translate((0.0, 0.0, h.z0))
    out = man.to_mesh()
    return trimesh.Trimesh(vertices=np.asarray(out.vert_properties)[:, :3], faces=out.tri_verts)


def build_sprues(
    stem: Stem,
    feeders: list[Feeder] | Feeder,
    fillets: list[Sphere],
    branches: list[Branch] | None = None,
    vents: list[Vent] | None = None,
    hub: Hub | None = None,
) -> list[trimesh.Trimesh]:
    """stem (+hub), feeders recortados (+filete del anillo), troncos, nudos, varillas."""
    if isinstance(feeders, Feeder):
        feeders = [feeders]
    parts = [build_stem(stem)]
    if hub is not None:
        parts.append(build_hub(hub))
    parts += [build_ring_join(f, fillets) for f in feeders]
    parts += [build_branch(b) for b in branches or []]
    parts += [build_fillet(s) for s in fillets if s.role != "ring_join"]
    return parts


def build_vents(vents: list[Vent] | None) -> list[trimesh.Trimesh]:
    return [build_vent(v) for v in vents or []]


def sprue_parts_from(prop) -> list[trimesh.Trimesh]:
    """Todas las piezas no-anillo de una proposal (árbol + varillas)."""
    return build_sprues(prop.stem, prop.feeders, prop.fillets, prop.branches, None, prop.hub) + build_vents(prop.vents)


def ring_in_job_frame(ring: trimesh.Trimesh, transform) -> trimesh.Trimesh:
    m = ring.copy()
    m.apply_transform(np.asarray(transform, float))
    return m


def export_previews(
    ring_job: trimesh.Trimesh,
    sprues: list[trimesh.Trimesh],
    outdir: Path,
    vents: list[trimesh.Trimesh] | None = None,
) -> dict[str, str]:
    """preview_ring.stl, preview_sprues.stl (+ preview_vents.stl): piezas separadas para el slicer."""
    outdir.mkdir(parents=True, exist_ok=True)
    out = {}
    ring_p = outdir / "preview_ring.stl"
    sprue_p = outdir / "preview_sprues.stl"
    io.save_stl_atomic(ring_job, ring_p)
    io.save_stl_atomic(trimesh.util.concatenate(sprues), sprue_p)
    out["ring"] = str(ring_p.resolve())
    out["sprues"] = str(sprue_p.resolve())
    vent_p = outdir / "preview_vents.stl"
    if vents:
        io.save_stl_atomic(trimesh.util.concatenate(vents), vent_p)
        out["vents"] = str(vent_p.resolve())
    elif vent_p.exists():
        vent_p.unlink()
    return out
