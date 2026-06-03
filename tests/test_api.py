import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(test_db):
    # Import after env var is set by test_db fixture
    from server.main import app
    return TestClient(app)


def test_markers_high_zoom_returns_geojson(client):
    resp = client.get("/api/markers?bbox=10.0,36.0,11.0,37.5&zoom=8")
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 2
    for f in data["features"]:
        assert f["properties"]["type"] == "inscription"


def test_markers_low_zoom_returns_clusters(client):
    resp = client.get("/api/markers?bbox=-180,-90,180,90&zoom=4")
    assert resp.status_code == 200
    data = resp.json()
    for f in data["features"]:
        assert f["properties"]["type"] == "province_cluster"


def test_markers_bad_bbox_returns_400(client):
    resp = client.get("/api/markers?bbox=notvalid&zoom=8")
    assert resp.status_code == 400


def test_markers_nan_bbox_returns_400(client):
    resp = client.get("/api/markers?bbox=NaN,36.0,11.0,37.5&zoom=8")
    assert resp.status_code == 400


def test_markers_missing_params_returns_422(client):
    resp = client.get("/api/markers")
    assert resp.status_code == 422


def test_inscription_returns_detail(client):
    resp = client.get("/api/inscription/EDCS-00000001")
    assert resp.status_code == 200
    data = resp.json()
    assert data["edcs_id"] == "EDCS-00000001"
    assert data["findspot"] == "Carthago"
    assert "raw_text" in data
    assert "persons" in data


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


def test_cache_control_on_api_routes(client):
    resp = client.get("/api/markers?bbox=10.0,36.0,11.0,37.5&zoom=8")
    assert resp.headers.get("cache-control") == "no-store"


def test_flag_nonexistent_edcs_id_still_succeeds(client):
    # Intentional: flags are stored even for unknown edcs_ids (future pipeline runs may load them)
    resp = client.post("/api/flags", json={
        "edcs_id": "EDCS-GHOST-99999",
        "category": "other",
        "comment": "flagged before inscription loaded",
    })
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
