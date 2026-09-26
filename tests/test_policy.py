import json

import pytest
import rings

from spruegen.detect import features
from spruegen.plan import policy
from spruegen.pipeline import run_propose
from spruegen.schemas import Job, PolicyError, Profile, Stem


def test_feeder_diameter_clip():
    p = Profile()
    assert policy.feeder_diameter(1.0, p) == 2.4
    assert policy.feeder_diameter(2.5, p) == pytest.approx(3.0)
    assert policy.feeder_diameter(5.0, p) == 3.5


def test_override_of_locked_key_rejected():
    job = Job(overrides={"stem_h_mm": 30.0})
    with pytest.raises(PolicyError, match="bloqueadas"):
        policy.apply_overrides(Profile(), job)


def test_default_locks_apply_even_if_job_omits_them():
    # el job no bloquea stem_d_mm, pero el profile sí (locks por default)
    job = Job(lock=[], overrides={"stem_d_mm": 8.0})
    with pytest.raises(PolicyError, match="stem_d_mm"):
        policy.apply_overrides(Profile(), job)


def test_override_of_unlocked_key_allowed():
    prof, warns = policy.apply_overrides(Profile(), Job(overrides={"feeder_d_min_mm": 2.6}))
    assert prof.feeder_d_min_mm == 2.6 and warns


def test_check_locks_detects_change():
    prof = Profile()
    locked = policy.lock_values(prof, ["stem_d_mm", "stem_h_mm", "attach_mode", "keepout"])
    ok_stem = Stem(d_mm=10.0, h_mm=35.0, origin=[0, 0, 0], axis=[0, 0, 1])
    assert policy.check_locks(locked, ok_stem, prof) == []
    bad_stem = ok_stem.model_copy(update={"h_mm": 30.0})
    assert any("stem_h_mm" in b for b in policy.check_locks(locked, bad_stem, prof))


def test_plan_on_torus_honors_profile(tmp_path, profile_path):
    stl = tmp_path / "t.stl"
    rings.torus_ring().export(stl)
    prop = run_propose(stl, profile_path, None, tmp_path / "wd")
    p = prop.profile
    assert prop.locks_honored
    assert (prop.stem.d_mm, prop.stem.h_mm) == (10.0, 35.0)
    assert p.feeder_len_mm[0] <= prop.feeder.len_mm <= p.feeder_len_mm[1]
    assert p.feeder_angle_deg[0] - 1e-6 <= prop.feeder.angle_deg <= p.feeder_angle_deg[1] + 1e-6
    assert p.feeder_d_min_mm <= prop.feeder.d_mm <= p.feeder_d_max_mm
    assert 0.4 <= prop.feeder.penetration_mm <= 0.8
    # attach en -Y, a la altura del stem + caída del feeder; nudo sobre la tapa del stem
    assert prop.feeder.node[2] == pytest.approx(35.0)
    assert prop.ring_job["piece_height_mm"] <= p.ring_space_mm
    # propose nunca escribe out.stl
    assert not (tmp_path / "wd" / "out.stl").exists()
    assert (tmp_path / "wd" / "preview_ring.stl").exists()
    assert (tmp_path / "wd" / "preview_sprues.stl").exists()


def test_propose_with_locked_override_fails(tmp_path, profile_path):
    stl = tmp_path / "t.stl"
    rings.torus_ring().export(stl)
    job = tmp_path / "job.json"
    job.write_text(json.dumps({"stl": "t.stl", "overrides": {"stem_h_mm": 25.0}}))
    with pytest.raises(PolicyError):
        run_propose(None, profile_path, job, tmp_path / "wd")
