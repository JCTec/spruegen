"""Stem editable y opcional: downstem de otra medida, o stub corto en vez de downstem."""

import math

import pytest
from typer.testing import CliRunner

from spruegen.cli import app
from spruegen.pipeline import apply_stem_cli, run_apply, run_propose
from spruegen.plan import policy
from spruegen.schemas import InputError, Job, PolicyError, Profile

runner = CliRunner()


def test_resolve_stem_swaps_in_stub_size():
    p = Profile(stem_kind="stub", stub_d_mm=6.0, stub_h_mm=5.0)
    r = policy.resolve_stem(p)
    assert (r.stem_d_mm, r.stem_h_mm) == (6.0, 5.0)
    assert policy.resolve_stem(Profile()) == Profile()


def test_stub_narrower_than_feeder_rejected():
    with pytest.raises(ValueError, match="más angosto que un feeder"):
        Profile(stem_kind="stub", stub_d_mm=2.0)


def test_job_cannot_switch_to_stub():
    with pytest.raises(PolicyError, match="stem_kind"):
        policy.apply_overrides(Profile(), Job(overrides={"stem_kind": "stub"}))


def test_apply_stem_cli_parsing():
    assert apply_stem_cli(Profile(), "off").stem_kind == "stub"
    p = apply_stem_cli(Profile(), "12×40")
    assert (p.stem_kind, p.stem_d_mm, p.stem_h_mm) == ("downstem", 12.0, 40.0)
    for bad in ("banana", "12x", "1x40"):
        with pytest.raises(InputError):
            apply_stem_cli(Profile(), bad)


@pytest.mark.parametrize("tree,feeders", [(None, None), ("spider", 3), ("y", 2)])
def test_stub_tree_validates(tmp_path, torus_stl, profile_path, tree, feeders):
    prop = run_propose(torus_stl, profile_path, None, tmp_path, tree, feeders, None, "off")
    assert (prop.stem.kind, prop.stem.d_mm, prop.stem.h_mm) == ("stub", 6.0, 5.0)
    assert prop.hub is None
    for f in prop.feeders:
        if f.node_kind == "stem":
            assert math.hypot(f.node[0], f.node[1]) <= 3.0  # los feeders convergen sobre el stub
    rep = run_apply(tmp_path / "proposal.json", tmp_path / "out.stl")
    assert rep["ok"], rep["errors"]
    assert rep["metrics"]["bodies"] == 1
    assert rep["metrics"]["stem"]["d_mm"] == pytest.approx(6.0, abs=0.2)


def test_stub_uses_less_metal(tmp_path, torus_stl, torus_run, profile_path):
    prop = run_propose(torus_stl, profile_path, None, tmp_path, None, None, None, "off")
    assert prop.casting["mass"]["tree_g"] < torus_run["prop"].casting["mass"]["tree_g"]


def test_custom_downstem_size(tmp_path, torus_stl, profile_path):
    prop = run_propose(torus_stl, profile_path, None, tmp_path, None, None, None, "12x40")
    assert prop.feeder.node[2] == pytest.approx(40.0)
    rep = run_apply(tmp_path / "proposal.json", tmp_path / "out.stl")
    assert rep["ok"], rep["errors"]
    st = rep["metrics"]["stem"]
    assert st["d_mm"] == pytest.approx(12.0, abs=0.2) and st["h_mm"] == pytest.approx(40.0, abs=0.5)
    assert not any("override" in w for w in rep["warnings"])


def test_cli_stem_option(tmp_path, torus_stl):
    r = runner.invoke(app, ["propose", str(torus_stl), "-o", str(tmp_path / "a"), "--stem", "off"])
    assert r.exit_code == 0, r.output
    assert "stub:" in r.output and "Ø6.0 x 5.0" in r.output
    r = runner.invoke(app, ["propose", str(torus_stl), "-o", str(tmp_path / "b"), "--stem", "banana"])
    assert r.exit_code == 2 and "--stem" in r.output
