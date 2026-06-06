import json
import sqlite3
import pytest
import server.db as db


def test_tile_high_zoom_returns_inscriptions(test_db):
    # z=8 tile (135, 99) covers both Africa inscriptions (tile_x=541,542 tile_y=398,399 at z=10
    # → at z=8 that's 541//4=135, 398//4=99)
    result = db.get_markers_for_tile(z=8, x=135, y=99)
    assert result["type"] == "FeatureCollection"
    ids = {f["properties"]["edcs_id"] for f in result["features"]}
    assert ids == {"EDCS-00000001", "EDCS-00000002"}


def test_tile_excludes_other_region(test_db):
    # z=8 tile (127, 85) covers Britannia only
    result = db.get_markers_for_tile(z=8, x=127, y=85)
    assert len(result["features"]) == 1
    assert result["features"][0]["properties"]["edcs_id"] == "EDCS-00000003"


def test_tile_high_zoom_exact_match(test_db):
    # Request the exact z=10 tile for EDCS-00000001 (541, 399)
    result = db.get_markers_for_tile(z=10, x=541, y=399)
    ids = {f["properties"]["edcs_id"] for f in result["features"]}
    assert "EDCS-00000001" in ids


def test_province_zoom_returns_clusters(test_db):
    # Zoom < 5 returns precomputed province summaries
    result = db.get_markers_for_tile(z=4, x=0, y=0)
    for feature in result["features"]:
        assert feature["properties"]["type"] == "province_cluster"
        assert "count" in feature["properties"]
        assert "province" in feature["properties"]


def test_province_zoom_returns_all_provinces(test_db):
    result = db.get_markers_for_tile(z=4, x=0, y=0)
    provinces = {f["properties"]["province"] for f in result["features"]}
    assert provinces == {"africa_proconsularis", "britannia"}


def test_aggregate_zoom7_direct(test_db):
    # z=7 tile (67,49) directly returns africa area_cluster
    result = db.get_markers_for_tile(z=7, x=67, y=49)
    features = result["features"]
    assert len(features) == 1
    p = features[0]["properties"]
    assert p["type"] == "area_cluster"
    assert p["count"] == 2
    assert p["tile_z"] == 7
    assert p["tile_x"] == 67
    assert p["tile_y"] == 49


def test_aggregate_zoom6_expands_to_z7(test_db):
    # z=6 tile (33,24) covers z=7 tiles (66-67, 48-49) → contains africa
    result = db.get_markers_for_tile(z=6, x=33, y=24)
    types = {f["properties"]["type"] for f in result["features"]}
    assert types == {"area_cluster"}
    counts = [f["properties"]["count"] for f in result["features"]]
    assert 2 in counts  # africa has count=2


def test_aggregate_zoom5_expands_to_z7(test_db):
    # z=5 tile (16,12) covers z=7 tiles (64-67, 48-51) → africa only
    result = db.get_markers_for_tile(z=5, x=16, y=12)
    assert any(f["properties"]["count"] == 2 for f in result["features"])


def test_aggregate_empty_tile_returns_empty(test_db):
    result = db.get_markers_for_tile(z=7, x=0, y=0)
    assert result["features"] == []


def test_individual_zoom_does_not_return_aggregates(test_db):
    # z=8 and above should never return area_cluster features
    result = db.get_markers_for_tile(z=8, x=135, y=99)
    for f in result["features"]:
        assert f["properties"]["type"] == "inscription"


def test_inscription_properties_present(test_db):
    result = db.get_markers_for_tile(z=10, x=541, y=399)
    feat = next(f for f in result["features"] if f["properties"]["edcs_id"] == "EDCS-00000001")
    props = feat["properties"]
    assert props["type"] == "inscription"
    assert "findspot" in props
    assert "person_names" in props
    assert "person_count" in props
    assert "genders" in props
    assert "edcs_url" in props
    assert "has_translation" in props


def test_get_markers_with_filters(test_db):
    # Test gender filter: EDCS-00000001 has persons of unknown gender, EDCS-00000002 has a male person
    res = db.get_markers_for_tile(z=10, x=541, y=398, gender="male")
    ids = {f["properties"]["edcs_id"] for f in res["features"]}
    assert "EDCS-00000002" in ids

    res_female = db.get_markers_for_tile(z=10, x=541, y=398, gender="female")
    assert len(res_female["features"]) == 0

    # Test search filter
    res_search = db.get_markers_for_tile(z=10, x=541, y=398, search="mar")
    ids_search = {f["properties"]["edcs_id"] for f in res_search["features"]}
    assert "EDCS-00000002" in ids_search # Marcus Tullius Cicero
    res_search_none = db.get_markers_for_tile(z=10, x=541, y=398, search="caesar")
    assert len(res_search_none["features"]) == 0


def test_has_translation_flag_when_present(test_db):
    result = db.get_markers_for_tile(z=10, x=541, y=398)
    feat = next(f for f in result["features"] if f["properties"]["edcs_id"] == "EDCS-00000002")
    assert feat["properties"]["has_translation"] is True


def test_get_inscription_returns_full_detail(test_db):
    result = db.get_inscription("EDCS-00000001")
    assert result is not None
    assert result["edcs_id"] == "EDCS-00000001"
    assert result["findspot"] == "Carthago"
    assert result["raw_text"] == "M. Tullio..."
    assert isinstance(result["persons"], list)
    assert result["has_overrides"] is False
    assert "translation" in result
    assert "summary" in result


def test_get_inscription_returns_none_for_missing(test_db):
    assert db.get_inscription("EDCS-NOTEXIST") is None


def test_get_inscription_uses_overrides_when_set(test_db):
    conn = sqlite3.connect(test_db)
    conn.execute(
        "UPDATE inscriptions SET overrides = ? WHERE edcs_id = ?",
        (json.dumps([{"nomen": "Corrected"}]), "EDCS-00000001"),
    )
    conn.commit()
    conn.close()

    result = db.get_inscription("EDCS-00000001")
    assert result["persons"] == [{"nomen": "Corrected"}]
    assert result["has_overrides"] is True


def test_insert_flag_stores_record(test_db):
    db.insert_flag("EDCS-00000001", "translation", "The ablative is wrong", "scholar@uni.edu")
    conn = sqlite3.connect(test_db)
    row = conn.execute("SELECT * FROM flags WHERE edcs_id = ?", ("EDCS-00000001",)).fetchone()
    assert row is not None
    assert row[2] == "translation"
    assert row[3] == "The ablative is wrong"
    assert row[4] == "scholar@uni.edu"
    conn.close()


def test_insert_flag_accepts_null_email_and_comment(test_db):
    db.insert_flag("EDCS-00000002", "other", None, None)
    conn = sqlite3.connect(test_db)
    count = conn.execute("SELECT COUNT(*) FROM flags").fetchone()[0]
    assert count == 1
    conn.close()
