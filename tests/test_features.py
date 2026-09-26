import math

import numpy as np
import pytest
import rings
import trimesh

from spruegen import features, io, repair
from spruegen.schemas import FeatureError, InputError, Profile


def _radial(feats, p):
    ax, c = np.array(feats.axis), np.array(feats.center)
    q = np.asarray(p) - c
    return np.linalg.norm(q - (q @ ax) * ax)


def test_torus_axis_center_and_inner_attach():
    ring = rings.torus_ring(19.0, 2.0)
    f = features.detect(ring, Profile())
    assert abs(abs(f.axis[2]) - 1) < 1e-3
    assert np.allclose(f.center, 0, atol=0.05)
    assert f.inner_radius_mm == pytest.approx(9.5, abs=0.05)
    assert f.tunnel_open_frac == 1.0
    best = f.candidates[0]
    assert best.thickness_mm == pytest.approx(2.0, abs=0.05)
    # el attach está en la cara interna, no en la externa
    assert _radial(f, best.point) == pytest.approx(9.5, abs=0.05)
    assert best.r_inner_mm < best.r_outer_mm


def test_axis_found_on_tilted_ring():
    ring = rings.tilted(rings.torus_ring())
    f = features.detect(ring, Profile())
    true_axis = ring.copy()
    R = trimesh.transformations.euler_matrix(0.7, -0.4, 1.1)[:3, :3]
    assert abs(np.dot(f.axis, R @ [0, 0, 1])) > 0.999
    assert _radial(f, f.candidates[0].point) == pytest.approx(9.5, abs=0.05)


def test_carved_band_attach_inside_thick_sector():
    band = rings.carved_band()
    f = features.detect(band, Profile())
    best = f.candidates[0]
    p = np.array(best.point)
    # sector grueso en -Y; attach por DENTRO (r≈9.5), nunca en el exterior tallado (r≈12.4)
    assert p[1] < -8.5 and abs(p[0]) < 3.0
    assert _radial(f, p) == pytest.approx(9.5, abs=0.05)
    assert best.thickness_mm >= 1.6
    # ningún candidato en la zona delgada (lattice 1.0 mm)
    for c in f.candidates:
        assert c.thickness_mm >= 1.6


def test_all_thin_ring_has_no_attach():
    thin = trimesh.creation.annulus(r_min=9.5, r_max=10.5, height=4.0, sections=96)
    with pytest.raises(FeatureError, match="no hay attach interno"):
        features.detect(thin, Profile())


def test_head_detected_attach_opposite():
    f = features.detect(rings.head_ring(), Profile())
    assert f.head_detected
    p = np.array(f.candidates[0].point)
    assert p[0] < -8.0  # lado opuesto a la cabeza (+X)


def test_manual_attach_on_outer_face_rejected():
    ring = rings.torus_ring()
    f = features.detect(ring, Profile())
    with pytest.raises(FeatureError, match="EXTERNA"):
        features.manual_candidate(ring, f, [0.0, -11.4, 0.0], Profile())
    c = features.manual_candidate(ring, f, [0.0, -9.6, 0.0], Profile())
    assert c.point[1] == pytest.approx(-9.5, abs=0.05)


def test_inches_detected(tmp_path):
    ring = rings.torus_ring()
    ring.apply_scale(1 / 25.4)
    p = tmp_path / "inch.stl"
    ring.export(p)
    with pytest.raises(InputError, match="pulgadas"):
        io.check_units(io.load_stl(p))


def test_repair_fails_loud_on_open_mesh():
    with pytest.raises(InputError, match="watertight"):
        repair.repair(rings.open_torus())


def test_repair_fixes_inverted_normals():
    ring = rings.torus_ring()
    ring.invert()
    fixed, rep = repair.repair(ring)
    assert fixed.volume > 0
    assert rep["normals_fixed"]
