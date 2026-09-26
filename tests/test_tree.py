import math

import numpy as np
import pytest
import rings

from spruegen.cli import run_apply, run_propose


@pytest.fixture(scope="module")
def torus_path(tmp_path_factory):
    p = tmp_path_factory.mktemp("tr") / "torus.stl"
    rings.torus_ring().export(p)
    return p


def _angle(pt):
    return math.degrees(math.atan2(pt[1], pt[0])) % 360


def test_single_mode_matches_v01_geometry(torus_path, tmp_path):
    prop = run_propose(torus_path, None, None, tmp_path, tree_mode="single")
    f = prop.feeders[0]
    assert len(prop.feeders) == 1 and not prop.branches
    assert f.len_mm == pytest.approx(10.0, abs=0.05)
    assert f.d_mm == pytest.approx(2.4)
    assert prop.attach.point_job[1] < 0  # attach primario en -Y


def test_spider3_equal_and_spread(torus_path, tmp_path):
    prop = run_propose(torus_path, None, None, tmp_path, tree_mode="spider", feeders=3)
    assert len(prop.feeders) == 3
    Ls = [f.len_mm for f in prop.feeders]
    assert max(Ls) - min(Ls) < 0.05
    ds = {round(f.d_mm, 6) for f in prop.feeders}
    assert len(ds) == 1  # uniforme
    angs = sorted(_angle(f.attach) for f in prop.feeders)
    gaps = [(angs[(i + 1) % 3] - angs[i]) % 360 for i in range(3)]
    assert all(abs(g - 120) < 25 for g in gaps)
    rep = run_apply(tmp_path / "proposal.json", tmp_path / "out.stl")
    assert rep["ok"], rep["errors"]
    assert rep["metrics"]["bodies"] == 1


def test_y_branch_area_conservation(torus_path, tmp_path):
    prop = run_propose(torus_path, None, None, tmp_path, tree_mode="y", feeders=2)
    assert len(prop.branches) == 1
    b = prop.branches[0]
    arms = sum((prop.feeders[i].d_mm / 2) ** 2 for i in b.arms)
    assert (b.d_mm / 2) ** 2 >= arms * 0.98
    assert all(f.node_kind == "branch" for f in prop.feeders)
    # la bifurcación queda bajo el anillo y sobre el stem
    zB = b.end[2]
    assert prop.stem.h_mm < zB < prop.ring_job["z_span"][0]
    rep = run_apply(tmp_path / "proposal.json", tmp_path / "out.stl")
    assert rep["ok"], rep["errors"]
    assert rep["metrics"]["outer_surface_max_diff_mm"] < 0.05


def test_auto_dumbbell_validates(tmp_path):
    p = tmp_path / "db.stl"
    rings.dumbbell_ring().export(p)
    prop = run_propose(p, None, None, tmp_path / "wd")
    assert len(prop.feeders) >= 2
    assert prop.analysis and prop.analysis["coverage"] >= 0.95
    rep = run_apply(tmp_path / "wd" / "proposal.json", tmp_path / "out.stl")
    assert rep["ok"], rep["errors"]


def test_v1_proposal_still_loads_and_validates(torus_path, tmp_path):
    import json

    from spruegen.schemas import load_proposal

    run_propose(torus_path, None, None, tmp_path, tree_mode="single")
    rep = run_apply(tmp_path / "proposal.json", tmp_path / "out.stl")
    d = json.loads((tmp_path / "proposal.json").read_text())
    f = d.pop("feeders")[0]
    ring = f.pop("ring_fillet")
    f.pop("node_kind")
    d["feeder"] = f
    d["fillets"].append(ring)
    for k in ("attaches", "branches", "vents", "hub", "tree", "analysis", "schema_version"):
        d.pop(k, None)
    v1 = tmp_path / "v1.json"
    v1.write_text(json.dumps(d))
    prop = load_proposal(v1)
    assert len(prop.feeders) == 1 and prop.feeders[0].ring_fillet is not None
    rep2 = run_apply(v1, tmp_path / "out_v1.stl")
    assert rep2["ok"], rep2["errors"]
