import json

import pytest
import rings
from typer.testing import CliRunner

from spruegen.config import presets
from spruegen.cli import app
from spruegen.pipeline import run_batch

runner = CliRunner()


def test_presets_available_and_loadable():
    names = presets.available()
    for n in ("ag925", "ag925_centrifugal", "au14k", "au18k", "bronze", "brass"):
        assert n in names
    assert presets.load("bronze").vents.mode == "auto"
    assert presets.load(None).metal == "Ag925"


def test_profile_commands(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = runner.invoke(app, ["profile", "list"])
    assert r.exit_code == 0 and "au14k" in r.output
    r = runner.invoke(app, ["profile", "show", "au14k"])
    assert json.loads(r.output)["metal"] == "Au14k"
    r = runner.invoke(app, ["profile", "new", "mi_taller", "--from", "au14k"])
    assert r.exit_code == 0 and (tmp_path / "profiles" / "mi_taller.json").exists()
    assert presets.load("mi_taller").metal == "Au14k"
    r = runner.invoke(app, ["profile", "show", "no_existe"])
    assert r.exit_code == 2


def test_analyze_render_log_roundtrip(tmp_path):
    stl = tmp_path / "t.stl"
    rings.torus_ring().export(stl)
    r = runner.invoke(app, ["analyze", str(stl), "-o", str(tmp_path / "an")])
    assert r.exit_code == 0, r.output
    assert (tmp_path / "an" / "analysis.json").exists()
    assert (tmp_path / "an" / "analysis.png").exists()
    assert list((tmp_path / "an").glob("zone_*.stl"))
    wd = tmp_path / "wd"
    r = runner.invoke(app, ["propose", str(stl), "-o", str(wd), "--tree", "spider", "--feeders", "2"])
    assert r.exit_code == 0, r.output
    r = runner.invoke(app, ["render", str(wd / "proposal.json")])
    assert r.exit_code == 0, r.output
    assert (wd / "render.png").exists() and (wd / "card.html").exists()
    log = tmp_path / "casts.jsonl"
    r = runner.invoke(app, ["log", "add", str(wd / "proposal.json"), "--result", "porosity", "--note", "x",
                            "--log", str(log)])
    assert r.exit_code == 0, r.output
    r = runner.invoke(app, ["log", "summary", "--log", str(log)])
    assert "Ag925" in r.output and "porosity" in r.output
    r = runner.invoke(app, ["log", "add", str(wd / "proposal.json"), "--result", "maso", "--log", str(log)])
    assert r.exit_code == 2


def test_batch(tmp_path):
    d = tmp_path / "rings"
    d.mkdir()
    rings.torus_ring().export(d / "a.stl")
    rings.plain_band().export(d / "b.stl")
    rows = run_batch(d, None, tmp_path / "out", True)
    assert [r["ok"] for r in rows] == [True, True]
    assert (tmp_path / "out" / "summary.csv").exists()
    assert (tmp_path / "out" / "a" / "out.stl").exists()


def test_bad_tree_flag():
    r = runner.invoke(app, ["propose", "x.stl", "--tree", "bosque"])
    assert r.exit_code == 2


@pytest.mark.slow
def test_demo_gallery(tmp_path):
    from spruegen.report import showcase

    ok = showcase.run_demo(tmp_path, echo=lambda *_: None)
    assert ok
    html = (tmp_path / "index.html").read_text()
    for name, *_ in showcase.CASES:
        assert name in html
        assert (tmp_path / name / "out.stl").exists()
