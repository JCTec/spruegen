"""Casting sheet: what the alloy database says about *this* tree.

Deterministic and advisory: it never changes the geometry. It reports metal mass, pour / flask
temperature windows for the ring's section class, and checks the planned feeders against published
sprueing rules — every number and rule with its citation.
"""

from __future__ import annotations

from typing import Any

from spruegen.materials.db import Alloy, AlloyDB, load

# Legor / Rio Grande split pour & flask temperatures by wall thickness (<0.5, 0.5–1.2, >1.2 mm)
THIN_MAX_MM = 0.5
MEDIUM_MAX_MM = 1.2
GYPSUM_RISK_C = 1200.0  # above this gypsum-bonded investment breaks down fast (rule: gypsum_breakdown)


def section_class(thickness_mm: float | None) -> str:
    if thickness_mm is None:
        return "medium"
    if thickness_mm < THIN_MAX_MM:
        return "thin"
    return "medium" if thickness_mm <= MEDIUM_MAX_MM else "heavy"


def _cited(v, unit: str, nd: int = 0) -> dict[str, Any] | None:
    if v is None:
        return None
    return {"min": v.lo, "max": v.hi, "text": v.fmt(unit, nd), "source": v.source, "locator": v.locator,
            **({"method": v.method} if v.method else {})}


def _rule_ratio(db: AlloyDB, rid: str, key: str, default: float) -> float:
    r = db.rule(rid)
    if r and isinstance(r.value, dict) and key in r.value:
        return float(r.value[key])
    return default


def sheet(
    alloy_id: str | None,
    *,
    ring_volume_mm3: float,
    tree_volume_mm3: float,
    section_thickness_mm: float | None,
    feeders: list[tuple[float, float]],  # (feeder Ø, attach thickness) per feeder
    process: str | None = None,
    db: AlloyDB | None = None,
) -> dict[str, Any] | None:
    """Build the casting sheet; ``None`` when the profile names no alloy."""
    if not alloy_id:
        return None
    db = db or load()
    a: Alloy = db.get(alloy_id)
    used: set[str] = set()
    warnings: list[dict[str, Any]] = []
    notes: list[str] = []

    def track(v):
        if v is not None and not v.derived:
            used.add(v.source)
        return v

    rho = track(a.density_g_cm3)
    sec = section_class(section_thickness_mm)
    pour = track(a.pour_c(sec))
    flask = track(a.flask_c(sec))
    sol, liq = track(a.solidus_c), track(a.liquidus_c)

    mass = None
    if rho is not None:
        g_per_mm3 = rho.mid / 1000.0
        mass = {
            "density_g_cm3": _cited(rho, " g/cm³", 2),
            "ring_g": ring_volume_mm3 * g_per_mm3,
            "tree_g": tree_volume_mm3 * g_per_mm3,
            "total_g": (ring_volume_mm3 + tree_volume_mm3) * g_per_mm3,
            "note": "árbol ≈ stem + feeders + filetes (sin descontar el solape con el anillo); suma el botón según tu práctica",
        }

    # --- rule checks (advisory)
    r_min = _rule_ratio(db, "feeder_gt_section", "min_ratio", 1.0)
    r_rec = _rule_ratio(db, "feeder_125pct", "min_ratio", 1.25)
    for i, (d, t) in enumerate(feeders):
        if t <= 0:
            continue
        ratio = d / t
        if ratio < r_min:
            warnings.append({"code": "feeder_thinner_than_section", "rule": "feeder_gt_section",
                             "params": {"feeder": i + 1, "d_mm": d, "t_mm": t, "ratio": ratio},
                             "text": f"feeder #{i + 1} Ø{d:.2f} mm < espesor {t:.2f} mm que alimenta (ratio {ratio:.2f} < {r_min:g})"})
        elif ratio < r_rec:
            notes.append(f"feeder #{i + 1}: Ø/espesor = {ratio:.2f} (la guía de Hoover & Strong pide ≥ {r_rec:g})")

    if a.investment == "phosphate":
        warnings.append({"code": "phosphate_investment", "rule": "gypsum_breakdown", "params": {"alloy": a.id},
                         "text": f"{a.name}: requiere revestimiento aglomerado con fosfato (no yeso)"})
    elif pour is not None and pour.hi > GYPSUM_RISK_C:
        warnings.append({"code": "pour_above_gypsum_limit", "rule": "gypsum_breakdown",
                         "params": {"pour_max_c": pour.hi},
                         "text": f"colada hasta {pour.hi:.0f} °C: el yeso se descompone (SO₂) por encima de ~{GYPSUM_RISK_C:.0f} °C; "
                                 "considera revestimiento de fosfato"})

    for r in ("feeder_gt_section", "feeder_125pct", "gypsum_breakdown"):
        rr = db.rule(r)
        if rr and rr.source != "derived":
            used.add(rr.source)

    return {
        "alloy": {"id": a.id, "name": a.name, "family": a.family, "investment": a.investment,
                  "composition_wt_pct": a.composition_wt_pct},
        "process": process,
        "section_class": sec,
        "section_thickness_mm": section_thickness_mm,
        "solidus_c": _cited(sol, " °C"),
        "liquidus_c": _cited(liq, " °C"),
        "freezing_range_k": a.freezing_range_k,
        "pour_c": _cited(pour, " °C"),
        "flask_c": _cited(flask, " °C"),
        "mass": mass,
        "warnings": warnings,
        "notes": notes + [n["text"] for n in a.notes()[:3]],
        "sources": [{"id": s.id, "cite": s.cite(), "type": s.type} for s in db.bibliography(used)],
        "disclaimer": "Valores publicados (con cita) como punto de partida; verifica con la ficha técnica de tu proveedor.",
    }
