import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))

import rings  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "profiles" / "ag925.json"


@pytest.fixture(scope="session")
def profile_path():
    return PROFILE


@pytest.fixture(scope="session")
def torus_stl(tmp_path_factory):
    p = tmp_path_factory.mktemp("rings") / "torus.stl"
    rings.torus_ring().export(p)
    return p


@pytest.fixture(scope="session")
def torus_run(tmp_path_factory, torus_stl):
    """propose + apply del torus una sola vez para varios tests."""
    from spruegen.cli import run_apply, run_propose

    wd = tmp_path_factory.mktemp("work")
    prop = run_propose(torus_stl, PROFILE, None, wd)
    rep = run_apply(wd / "proposal.json", wd / "out.stl")
    return {"wd": wd, "prop": prop, "report": rep}
