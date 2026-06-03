import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(test_db):
    # Import after env var is set by test_db fixture
    from server.main import app
    return TestClient(app)


def test_tiles_high_zoom_returns_geojson(client):
    # z=8 tile (135,99) covers both Africa inscriptions
    resp = client.get("/api/tiles/8/135/99")
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 2
    for f in data["features"]:
        assert f["properties"]["type"] == "inscription"


def test_tiles_low_zoom_returns_clusters(client):
    resp = client.get("/api/tiles/4/0/0")
    assert resp.status_code == 200
    data = resp.json()
    for f in data["features"]:
        assert f["properties"]["type"] == "province_cluster"


def test_tiles_exact_z10_match(client):
    resp = client.get("/api/tiles/10/541/399")
    assert resp.status_code == 200
    ids = {f["properties"]["edcs_id"] for f in resp.json()["features"]}
    assert "EDCS-00000001" in ids


def test_tiles_cache_control_public(client):
    resp = client.get("/api/tiles/8/135/99")
    assert resp.headers.get("cache-control") == "public, max-age=86400"


def test_tiles_different_region_excluded(client):
    # Britannia tile should not contain Africa inscriptions
    resp = client.get("/api/tiles/8/127/85")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["features"]) == 1
    assert data["features"][0]["properties"]["edcs_id"] == "EDCS-00000003"


def test_tiles_translation_in_response(client):
    resp = client.get("/api/tiles/10/541/398")
    assert resp.status_code == 200
    features = resp.json()["features"]
    feat = next(f for f in features if f["properties"]["edcs_id"] == "EDCS-00000002")
    assert feat["properties"]["translation"] == "Translation for inscription 2"


def test_inscription_returns_detail(client):
    resp = client.get("/api/inscription/EDCS-00000001")
    assert resp.status_code == 200
    data = resp.json()
    assert data["edcs_id"] == "EDCS-00000001"
    assert data["findspot"] == "Carthago"
    assert "raw_text" in data
    assert "persons" in data
    assert "translation" in data
    assert "summary" in data


def test_inscription_not_found_returns_404(client):
    resp = client.get("/api/inscription/EDCS-NOTEXIST")
    assert resp.status_code == 404


def test_flag_valid_submission(client):
    resp = client.post("/api/flags", json={
        "edcs_id": "EDCS-00000001",
        "category": "translation",
        "comment": "The ablative is wrong",
        "email": "scholar@uni.edu",
    })
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_flag_minimal_submission(client):
    resp = client.post("/api/flags", json={
        "edcs_id": "EDCS-00000001",
        "category": "other",
    })
    assert resp.status_code == 200


def test_flag_invalid_category_returns_422(client):
    resp = client.post("/api/flags", json={
        "edcs_id": "EDCS-00000001",
        "category": "nonsense",
    })
    assert resp.status_code == 422


def test_flag_nonexistent_edcs_id_still_succeeds(client):
    resp = client.post("/api/flags", json={
        "edcs_id": "EDCS-GHOST-99999",
        "category": "other",
        "comment": "flagged before inscription loaded",
    })
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_inscription_cache_control_no_store(client):
    resp = client.get("/api/inscription/EDCS-00000001")
    assert resp.headers.get("cache-control") == "no-store"
