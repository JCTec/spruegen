import json
import shutil
from pathlib import Path

import numpy as np
import pytest
import trimesh
from typer.testing import CliRunner

from spruegen.construct import sprues as build
from spruegen.mesh import io
from spruegen.cli import app
from spruegen.pipeline import run_apply, run_propose
from spruegen.schemas import load_proposal
from spruegen.construct.validate import load_ring_job, validate

INPUT = Path(__file__).resolve().parents[2] / "input.stl"
runner = CliRunner()


def test_torus_done_criterion(torus_run):
    rep = torus_run["report"]
    assert rep["ok"], rep["errors"]
    out = trimesh.load(torus_run["wd"] / "out.stl")
    out.merge_vertices()
    assert out.is_watertight
    st = rep["metrics"]["stem"]
    assert st["d_mm"] == pytest.approx(10.0, abs=0.2)
    assert st["h_mm"] == pytest.approx(35.0, abs=0.5)
    assert st["z_base"] == pytest.approx(0.0, abs=1e-6)
    assert rep["metrics"]["outer_surface_max_diff_mm"] < 0.05
    assert rep["metrics"]["hole_blocked_frac"] < 0.5
    ring_vol = rep["metrics"]["ring_volume_mm3"]
    assert out.volume > ring_vol


def test_previews_are_separate(torus_run):
    wd = torus_run["wd"]
    ring = io.load_stl(wd / "preview_ring.stl")
    spr = io.load_stl(wd / "preview_sprues.stl")
    assert ring.bounds[0, 2] > 35.0  # el anillo está sobre la tapa del stem
    assert spr.bounds[0, 2] == pytest.approx(0.0, abs=1e-6)


def test_validate_detects_plugged_hole(torus_run):
    prop = torus_run["prop"]
    out = trimesh.load(torus_run["wd"] / "out.stl")
    ring_job = load_ring_job(prop)
    z0, z1 = ring_job.bounds[:, 2]
    plug = trimesh.creation.cylinder(radius=9.7, height=(z1 - z0) * 0.8, sections=64)
    plug.apply_translation([0, 0, (z0 + z1) / 2])
    plugged = trimesh.boolean.union([out, plug], engine="manifold")
    rep = validate(plugged, prop, ring_job)
    assert not rep["ok"]
    assert any("hueco" in e for e in rep["errors"])


def test_validate_detects_sprue_on_outer_face(torus_run):
    prop = torus_run["prop"]
    out = trimesh.load(torus_run["wd"] / "out.stl")
    ring_job = load_ring_job(prop)
    zc = ring_job.bounds[:, 2].mean()
    blob = trimesh.creation.icosphere(radius=1.2)
    blob.apply_translation([0, 11.4, zc])
    rep = validate(trimesh.boolean.union([out, blob], engine="manifold"), prop, ring_job)
    assert not rep["ok"]
    assert any("cara externa" in e for e in rep["errors"])


def test_validate_detects_bare_ring_and_wrong_stem(torus_run):
    prop = torus_run["prop"]
    ring_job = load_ring_job(prop)
    stem = trimesh.creation.cylinder(radius=6.0, height=30.0, sections=48)
    stem.apply_translation([0, 0, 15.0])
    rep = validate(trimesh.util.concatenate([ring_job, stem]), prop, ring_job)
    errs = " ".join(rep["errors"])
    assert "Ø12" in errs and "alto" in errs


def test_validate_detects_lock_violation(torus_run, tmp_path):
    wd = torus_run["wd"]
    data = json.loads((wd / "proposal.json").read_text())
    data["stem"]["h_mm"] = 30.0  # alguien editó la proposal a mano
    bad = tmp_path / "proposal.json"
    bad.write_text(json.dumps(data))
    prop = load_proposal(bad)
    out = trimesh.load(wd / "out.stl")
    rep = validate(out, prop)
    assert any("locks violados" in e for e in rep["errors"])


def test_apply_failure_does_not_write_out(torus_run, tmp_path):
    wd = torus_run["wd"]
    data = json.loads((wd / "proposal.json").read_text())
    data["stem"]["d_mm"] = 14.0  # viola lock -> validate falla
    p = tmp_path / "proposal.json"
    p.write_text(json.dumps(data))
    rep = run_apply(p, tmp_path / "out.stl")
    assert not rep["ok"]
    assert not (tmp_path / "out.stl").exists()
    assert not list(tmp_path.glob("*.tmp"))


def test_cli_end_to_end(torus_stl, profile_path, tmp_path):
    wd = tmp_path / "wd"
    r = runner.invoke(app, ["inspect", str(torus_stl)])
    assert r.exit_code == 0, r.output
    assert json.loads(r.output)["features"]["candidates"]
    r = runner.invoke(app, ["propose", str(torus_stl), "-p", str(profile_path), "-o", str(wd)])
    assert r.exit_code == 0, r.output
    assert not (tmp_path / "out.stl").exists()
    r = runner.invoke(app, ["apply", str(wd / "proposal.json"), "-o", str(tmp_path / "out.stl")])
    assert r.exit_code == 0, r.output
    r = runner.invoke(app, ["validate", str(tmp_path / "out.stl"), "--proposal", str(wd / "proposal.json")])
    assert r.exit_code == 0, r.output


def test_cli_exit_codes(tmp_path, profile_path):
    thin = trimesh.creation.annulus(r_min=9.5, r_max=10.5, height=4.0, sections=96)
    p = tmp_path / "thin.stl"
    thin.export(p)
    r = runner.invoke(app, ["propose", str(p), "-p", str(profile_path), "-o", str(tmp_path / "wd")])
    assert r.exit_code == 2
    assert "no hay attach interno" in r.output


@pytest.mark.skipif(not INPUT.exists(), reason="no hay ../input.stl")
def test_real_input_ring(tmp_path, profile_path):
    prop = run_propose(INPUT, profile_path, None, tmp_path)
    rep = run_apply(tmp_path / "proposal.json", tmp_path / "out.stl")
    assert rep["ok"], rep["errors"]
    assert rep["metrics"]["outer_surface_max_diff_mm"] < 0.05
