import io
import zipfile

import pytest
import rings

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from spruegen.gui import i18n, server  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "ROOT", tmp_path / "gui")
    return TestClient(server.app)


def _upload(client, mesh, name="ring.stl"):
    data = mesh.export(file_type="stl")
    return client.post("/api/session", files={"file": (name, io.BytesIO(data), "model/stl")})


def test_index_and_presets(client):
    r = client.get("/")
    assert r.status_code == 200 and "spruegen" in r.text
    names = [p["name"] for p in client.get("/api/presets").json()]
    assert "ag925" in names and "bronze" in names


def test_full_flow_torus(client):
    r = _upload(client, rings.torus_ring(), "My Ring.stl")
    assert r.status_code == 200, r.text
    j = r.json()
    sid = j["sid"]
    assert j["summary"]["inner_d_mm"] == pytest.approx(19.0, abs=0.1)
    assert client.get(f"/api/{sid}/file/{j['mesh_url']}").status_code == 200
    # export before generate -> 409
    assert client.get(f"/api/{sid}/export/stl").status_code == 409

    cfg = {"preset": "ag925", "tree_mode": "auto", "vents": "auto", "advanced": {}}
    a = client.post(f"/api/{sid}/analyze", json=cfg)
    assert a.status_code == 200, a.text
    aj = a.json()
    assert aj["feeder_count"] == 1 and aj["zones"]
    assert aj["reasons"][0].startswith("coverage")  # translated
    assert client.get(f"/api/{sid}/file/{aj['zones'][0]['url']}").status_code == 200

    g = client.post(f"/api/{sid}/generate", json=cfg)
    assert g.status_code == 200, g.text
    gj = g.json()
    assert gj["ok"] and all(c["ok"] for c in gj["validation"]["checks"])
    assert gj["vents"]
    for url in gj["meshes"].values():
        assert client.get(f"/api/{sid}/file/{url}").status_code == 200

    e = client.get(f"/api/{sid}/export/stl")
    assert e.status_code == 200 and "Ring_sprued.stl" in e.headers["content-disposition"]
    z = client.get(f"/api/{sid}/export/zip")
    assert z.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
    assert any(n.endswith("_sprued.stl") for n in names) and any(n.endswith("proposal.json") for n in names)


def test_spider_and_advanced(client):
    sid = _upload(client, rings.torus_ring()).json()["sid"]
    cfg = {"preset": "ag925", "tree_mode": "spider", "feeders": 3, "vents": "off",
           "advanced": {"feeder_d_min_mm": 2.6}}
    gj = client.post(f"/api/{sid}/generate", json=cfg).json()
    assert len(gj["feeders"]) == 3
    assert all(f["d_mm"] >= 2.6 - 1e-9 for f in gj["feeders"])
    bad = client.post(f"/api/{sid}/generate", json={**cfg, "advanced": {"feeder_d_min_mm": 9, "feeder_d_max_mm": 3}})
    assert bad.status_code == 400 and "error" in bad.json()


def test_inch_file_rejected_in_english(client):
    m = rings.torus_ring()
    m.apply_scale(1 / 25.4)
    r = _upload(client, m)
    assert r.status_code == 400
    assert r.json()["error"].startswith("Possible STL in inches")


def test_file_whitelist(client):
    sid = _upload(client, rings.torus_ring()).json()["sid"]
    assert client.get(f"/api/{sid}/file/../../etc/passwd").status_code == 404
    assert client.get(f"/api/{sid}/file/profile.py").status_code == 404
    assert client.get("/api/nope/file/x.stl").status_code == 404


def test_translation_fallback():
    assert i18n.translate("algo nuevo sin traducir") == "algo nuevo sin traducir"
    assert "dropped the spot" in i18n.translate(
        "se descartó el attach cerca de theta=54° (el feeder queda a 0.13 mm de la cara externa (mín. 0.3 mm): "
        "el shank es delgado alrededor del attach); quedan 1 feeders")
