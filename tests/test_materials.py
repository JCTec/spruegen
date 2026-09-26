"""Alloy database: integrity (every number cited), loader API, preset wiring, casting sheet."""

import json

import pytest

from spruegen import materials
from spruegen.config import presets
from spruegen.materials import casting
from spruegen.materials.db import DERIVED
from spruegen.schemas import InputError, load_profile

NUMERIC_KEYS = ("value", "min", "max")


def _numbers_without_source(node, inherited=None, path=""):
    """Yield paths of numeric leaves that have no `source` on their own dict or an ancestor dict."""
    if isinstance(node, dict):
        src = node.get("source", inherited)
        for k, v in node.items():
            if k in ("composition_wt_pct", "composition_source", "fineness"):
                continue
            if k in NUMERIC_KEYS and isinstance(v, (int, float, list)) and src is None:
                yield f"{path}.{k}"
            else:
                yield from _numbers_without_source(v, src, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _numbers_without_source(v, inherited, f"{path}[{i}]")


def test_bundled_db_integrity():
    db = materials.load()
    assert len(db.alloys) >= 20 and len(db.sources) >= 30
    assert materials.check(db) == []


def test_every_number_is_cited():
    raw = json.loads((materials.db.resources.files("spruegen.materials") / "data" / "alloys.json").read_text())
    missing = [p for a_id, a in raw["alloys"].items()
               for p in _numbers_without_source(a.get("properties", {}), None, a_id)]
    assert missing == []


def test_derived_values_explain_method():
    db = materials.load()
    for a in db.alloys.values():
        for key in a.raw.get("properties", {}):
            v = a.prop(key)
            if v is not None and v.source == DERIVED:
                assert v.method, f"{a.id}.{key} derived without method"


def test_sterling_core_values():
    a = materials.load().get("ag925")
    assert 10.2 <= a.density_g_cm3.mid <= 10.5
    assert 770 <= a.solidus_c.mid < a.liquidus_c.mid <= 910
    assert a.pour_c("thin").lo > a.liquidus_c.mid  # superheat
    assert a.flask_c("thin").lo >= a.flask_c("heavy").lo  # thin work = hotter flask


def test_platinum_needs_phosphate():
    assert materials.load().get("pt950ru").investment == "phosphate"


def test_unknown_alloy_is_actionable():
    with pytest.raises(InputError, match="aleación desconocida"):
        materials.load().get("unobtainium")


def test_every_preset_points_at_a_real_alloy():
    db = materials.load()
    for name, p in presets.available().items():
        assert p.alloy in db.alloys, name


def test_preset_inheritance(tmp_path):
    child = tmp_path / "mine.json"
    child.write_text(json.dumps({"extends": "au14k", "tree": {"feed_reach_mm": 25}}))
    p = load_profile(child)
    base = presets.load("au14k")
    assert p.alloy == "au14y" and p.feeder_d_min_mm == base.feeder_d_min_mm
    assert p.tree.feed_reach_mm == 25 and p.tree.feeder_capacity_mm3 == base.tree.feeder_capacity_mm3


def test_preset_inheritance_cycle(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps({"extends": "b"}))
    (tmp_path / "b.json").write_text(json.dumps({"extends": "a"}))
    with pytest.raises(InputError, match="circular"):
        load_profile(tmp_path / "a.json")


def test_casting_sheet_sterling():
    s = casting.sheet("ag925", ring_volume_mm3=300.0, tree_volume_mm3=2900.0, section_thickness_mm=1.8,
                      feeders=[(2.4, 2.0)], process="vacuum")
    assert s["section_class"] == "heavy"
    assert s["mass"]["ring_g"] == pytest.approx(300 * 10.4 / 1000, rel=0.02)
    assert s["pour_c"]["source"] and s["flask_c"]["source"]
    assert s["sources"] and all(src["cite"] for src in s["sources"])
    assert not [w for w in s["warnings"] if w["code"] == "feeder_thinner_than_section"]


def test_casting_sheet_flags_thin_feeder_and_phosphate():
    s = casting.sheet("pt950ru", ring_volume_mm3=300.0, tree_volume_mm3=2900.0, section_thickness_mm=0.4,
                      feeders=[(2.0, 2.5)])
    codes = {w["code"] for w in s["warnings"]}
    assert {"feeder_thinner_than_section", "phosphate_investment"} <= codes
    assert s["section_class"] == "thin"


def test_casting_sheet_without_alloy_is_none():
    assert casting.sheet(None, ring_volume_mm3=1, tree_volume_mm3=1, section_thickness_mm=1, feeders=[]) is None


@pytest.mark.parametrize("t,cls", [(0.3, "thin"), (0.5, "medium"), (1.2, "medium"), (1.3, "heavy"), (None, "medium")])
def test_section_class(t, cls):
    assert casting.section_class(t) == cls
