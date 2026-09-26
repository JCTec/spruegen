"""Varillas de rebalse / venteo en el extremo lejano del anillo.

Al imprimir quedan arriba (lejos del stem); al colar el cilindro se invierte y quedan abajo: el metal
recorre todo el anillo y termina en las varillas, que se llevan el aire y el primer metal frío.

Cada varilla es paralela al eje del dedo, pegada a la cara interna junto al canto lejano (nunca toca la
cara externa), y se recorta con un cilindro coaxial r_interno + pen, igual que los feeders.
"""

from __future__ import annotations

import math

import numpy as np

from . import build
from .features import OuterGrid, angdist, plane_basis, probe
from .policy import SKIN_MARGIN_MM
from .schemas import Features, Profile, Vent

SHIFT_STEPS_DEG = [0, 3, -3, 6, -6, 10, -10, 15, -15, 20, -20]


def vent_angles(p: Profile, feeder_thetas: list[float], last_to_fill: list[dict] | None) -> list[float]:
    """Ángulos (frame de entrada, grados) para las varillas."""
    vc = p.vents
    n = vc.count
    if vc.mode == "auto" and last_to_fill:
        return [t["theta_deg"] for t in last_to_fill[:n]]
    # sin análisis: repartidas en los huecos angulares más grandes entre feeders
    if not feeder_thetas:
        return [k * 360.0 / n for k in range(n)]
    ths = sorted(t % 360.0 for t in feeder_thetas)
    gaps = [((ths[(i + 1) % len(ths)] - ths[i]) % 360.0 or 360.0, ths[i]) for i in range(len(ths))]
    gaps.sort(reverse=True)
    out = []
    for k in range(n):
        g, start = gaps[k % len(gaps)]
        reps = n // len(gaps) + (1 if k % len(gaps) < n % len(gaps) else 0)
        j = k // len(gaps) + 1
        out.append(start + g * j / (reps + 1))
    return out


def plan_vents(ring_in, feats: Features, grid: OuterGrid | None, T: np.ndarray, p: Profile,
               feeder_thetas: list[float], last_to_fill: list[dict] | None) -> tuple[list[Vent], list[str]]:
    vc = p.vents
    warnings: list[str] = []
    if vc.mode == "off":
        return [], warnings
    axis = np.array(feats.axis)
    c = np.array(feats.center)
    u, v = plane_basis(axis)
    hmax = float(((ring_in.vertices - c) @ axis).max())
    R = vc.d_mm / 2
    placed: list[Vent] = []
    Rm, t = T[:3, :3], T[:3, 3]
    for tgt in vent_angles(p, feeder_thetas, last_to_fill):
        done = False
        for dth in SHIFT_STEPS_DEG:
            th = math.radians(tgt + dth)
            if any(float(angdist(th, math.radians(f))) < math.radians(25) for f in feeder_thetas):
                continue
            if any(float(angdist(th, math.radians(x.theta_deg))) < math.radians(vc.min_sep_deg) for x in placed):
                continue
            # canto lejano local: bajando desde arriba, primera altura con cara interna sólida
            # (el tope global puede ser una cabeza/garras, no el shank)
            found = None
            for h_try in np.arange(hmax - 0.3, 0.0, -0.2):
                r1, r2, n = probe(ring_in, feats, th, float(h_try))
                if n >= 2 and np.isfinite(r2) and (r2 - r1) >= vc.pen_mm + SKIN_MARGIN_MM:
                    found = (float(h_try), r1, r2)
                    break
            if found is None:
                continue
            h_edge, r1, r2 = found
            h_edge += 0.2
            d = math.cos(th) * u + math.sin(th) * v
            r_ax = r1 - R + vc.pen_mm
            base_in = c + (h_edge - vc.overlap_mm) * axis + r_ax * d
            top_in = c + (h_edge + vc.len_mm) * axis + r_ax * d
            vent = Vent(
                base=(Rm @ base_in + t).tolist(),
                top=(Rm @ top_in + t).tolist(),
                d_mm=vc.d_mm,
                clip_r_mm=r1 + vc.pen_mm,
                theta_deg=math.degrees(th),
                attach_thickness_mm=float(r2 - r1),
            )
            if grid is not None and "outer_surface" in p.keepout:
                rod = build.build_vent(vent)
                rod.apply_transform(np.linalg.inv(T))
                if grid.min_clearance(rod) < SKIN_MARGIN_MM:
                    continue
            placed.append(vent)
            done = True
            break
        if not done:
            warnings.append(f"no se pudo poner varilla cerca de theta={tgt:.0f}° (canto delgado o pegado a un feeder)")
    return placed, warnings
