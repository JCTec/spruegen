import math

import pytest
import rings

from spruegen.cli import run_apply, run_propose
from spruegen.features import angdist


@pytest.fixture(scope="module")
def band_path(tmp_path_factory):
    p = tmp_path_factory.mktemp("v") / "band.stl"
    rings.plain_band().export(p)
    return p


def test_two_vents_on_far_edge_inside(band_path, tmp_path):
    prop = run_propose(band_path, None, None, tmp_path, tree_mode="single", vents_opt="2")
    assert len(prop.vents) == 2
    top = prop.ring_job["z_span"][1]
    for v in prop.vents:
        assert v.top[2] > top + 3.0  # sobresale del canto lejano
        assert math.hypot(*v.base[:2]) < prop.features.inner_radius_mm + 0.5  # pegada por dentro
    a, b = (math.radians(v.theta_deg) for v in prop.vents)
    assert float(angdist(a, b)) >= math.radians(59)
    assert (tmp_path / "preview_vents.stl").exists()
    rep = run_apply(tmp_path / "proposal.json", tmp_path / "out.stl")
    assert rep["ok"], rep["errors"]
    assert rep["metrics"]["bodies"] == 1
    assert rep["metrics"]["outer_surface_max_diff_mm"] < 0.05
    assert rep["metrics"]["piece_height_mm"] <= prop.profile.ring_space_mm


def test_auto_vents_go_where_metal_arrives_last(band_path, tmp_path):
    prop = run_propose(band_path, None, None, tmp_path, tree_mode="auto", vents_opt="auto")
    assert prop.vents
    f = math.radians(prop.attach.theta_deg)
    # la primera varilla lejos del feeder (lado opuesto del aro)
    assert float(angdist(math.radians(prop.vents[0].theta_deg), f)) > math.radians(120)


def test_vents_off_by_default(band_path, tmp_path):
    prop = run_propose(band_path, None, None, tmp_path)
    assert prop.vents == []
