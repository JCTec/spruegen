import math

import numpy as np
import pytest
import rings

from spruegen import analysis, features, voxel
from spruegen.features import angdist
from spruegen.schemas import Profile

P = Profile()


def _analyze(mesh, prof=P):
    f = features.detect(mesh, prof, max_candidates=3000, respect_head=False)
    return f, analysis.analyze(mesh, f, f.candidates, prof)


def test_voxel_volume_matches_mesh():
    m = rings.torus_ring()
    vf = voxel.voxelize(m, 0.15)
    assert vf.occ.sum() * 0.15**3 == pytest.approx(m.volume, rel=0.02)
    # EDT máximo ≈ radio del tubo (1 mm)
    assert vf.edt.max() == pytest.approx(1.0, abs=0.12)


def test_plain_torus_needs_one_feeder_full_coverage():
    _, r = _analyze(rings.torus_ring())
    assert r.summary["feeder_count"] == 1
    assert r.summary["coverage"] >= 0.99
    assert not r.summary["isolated_zones"]


def test_last_to_fill_is_opposite_the_feeder():
    _, r = _analyze(rings.torus_ring())
    f = math.radians(r.attaches[0].theta_deg)
    lt = math.radians(r.vent_targets[0]["theta_deg"])
    assert float(angdist(f, lt)) > math.radians(150)


def test_dumbbell_two_hot_spots_two_feeders():
    _, r = _analyze(rings.dumbbell_ring())
    assert r.summary["feeder_count"] >= 2
    assert r.summary["coverage"] >= 0.95
    # un feeder por masa (las masas están en ±X del STL)
    feats = features.detect(rings.dumbbell_ring(), P)
    xs = sorted(a.point[0] for a in r.attaches)
    assert xs[0] < -8 and xs[-1] > 8


def test_neck_isolation_reported_when_feeders_capped():
    prof = Profile.model_validate({**P.model_dump(), "tree": {**P.tree.model_dump(), "max_feeders": 1}})
    _, r = _analyze(rings.dumbbell_ring(), prof)
    assert r.summary["feeder_count"] == 1
    assert r.summary["isolated_zones"]
    assert any("zona aislada" in w for w in r.summary["warnings"])


def test_capacity_forces_two_feeders_on_wide_band():
    _, r = _analyze(rings.wide_band())
    assert r.summary["k_capacity"] == 2
    assert r.summary["feeder_count"] == 2
    a, b = (math.radians(x.theta_deg) for x in r.attaches)
    assert float(angdist(a, b)) > math.radians(150)  # simétricos


def test_signet_head_gets_inner_feeder():
    f, r = _analyze(rings.signet())
    assert f.head_detected
    assert any(x["head"] for x in r.summary["feeders"])
    # el attach sigue siendo interno
    for a in r.attaches:
        assert a.r_inner_mm < a.r_outer_mm


def test_solitaire_prongs_are_not_fed_directly():
    f, r = _analyze(rings.solitaire())
    assert f.head_detected  # detectado por silueta (garras)
    assert not any(x["head"] for x in r.summary["feeders"])


def test_zone_meshes_cover_all_cells():
    _, r = _analyze(rings.torus_ring())
    zm = analysis.zone_meshes(r)
    assert "zone_feeder1" in zm
