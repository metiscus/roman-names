import json
import sqlite3
import pytest
import server.db as db


def test_bbox_returns_inscriptions_in_view(test_db):
    # Africa bbox — should return 2 inscriptions
    result = db.get_markers_in_bbox(west=10.0, south=36.0, east=11.0, north=37.5, zoom=8)
    assert result["type"] == "FeatureCollection"
    assert len(result["features"]) == 2
    ids = {f["properties"]["edcs_id"] for f in result["features"]}
    assert ids == {"EDCS-00000001", "EDCS-00000002"}


def test_bbox_excludes_out_of_view(test_db):
    # Britannia bbox — should not include Africa inscriptions
    result = db.get_markers_in_bbox(west=-1.0, south=51.0, east=0.5, north=52.0, zoom=8)
    assert len(result["features"]) == 1
    assert result["features"][0]["properties"]["edcs_id"] == "EDCS-00000003"


def test_low_zoom_returns_province_clusters(test_db):
    # Zoom < 6 over whole empire — expect province summaries, not individual inscriptions
    result = db.get_markers_in_bbox(west=-180, south=-90, east=180, north=90, zoom=4)
    for feature in result["features"]:
        assert feature["properties"]["type"] == "province_cluster"
        assert "count" in feature["properties"]
        assert "province" in feature["properties"]


def test_get_inscription_returns_full_detail(test_db):
    result = db.get_inscription("EDCS-00000001")
    assert result is not None
    assert result["edcs_id"] == "EDCS-00000001"
    assert result["findspot"] == "Carthago"
    assert result["raw_text"] == "M. Tullio..."
    assert isinstance(result["persons"], list)
    assert result["has_overrides"] is False


def test_get_inscription_returns_none_for_missing(test_db):
    assert db.get_inscription("EDCS-NOTEXIST") is None


def test_get_inscription_uses_overrides_when_set(test_db):
    # Manually set overrides
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
    assert row[2] == "translation"   # category
    assert row[3] == "The ablative is wrong"  # comment
    assert row[4] == "scholar@uni.edu"  # email
    conn.close()


def test_insert_flag_accepts_null_email_and_comment(test_db):
    db.insert_flag("EDCS-00000002", "other", None, None)
    conn = sqlite3.connect(test_db)
    count = conn.execute("SELECT COUNT(*) FROM flags").fetchone()[0]
    assert count == 1
    conn.close()
