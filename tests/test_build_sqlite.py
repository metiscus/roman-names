import importlib.util
import json
import sqlite3
from pathlib import Path
import pytest

# Import the numbered script via importlib (can't use normal import for files starting with digits)
_spec = importlib.util.spec_from_file_location(
    "build_sqlite",
    Path(__file__).parent.parent / "scripts" / "10_build_sqlite.py",
)
build_sqlite = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_sqlite)
build = build_sqlite.build


@pytest.fixture
def sample_geojson_dir(tmp_path):
    """Write two tiny province GeoJSON files for testing."""
    persons = [{"praenomen": "Marcus", "nomen": "Tullius", "cognomen": "Cicero",
                "gender": "male", "status": "senator", "cluster_id": 1,
                "cluster_size": 2, "cluster_confidence": "high"}]
    africa = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [10.2, 36.8]},
                "properties": {
                    "edcs_id": "EDCS-00000001",
                    "findspot": "Carthago",
                    "raw_text": "M. Tullio...",
                    "date_from": -50,
                    "date_to": 50,
                    "persons": persons,
                },
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [10.3, 36.9]},
                "properties": {
                    "edcs_id": "EDCS-00000002",
                    "findspot": "Carthago",
                    "raw_text": "L. Bruto...",
                    "date_from": 0,
                    "date_to": 100,
                    "persons": persons,
                },
            },
        ],
    }
    britannia = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-0.1, 51.5]},
                "properties": {
                    "edcs_id": "EDCS-00000003",
                    "findspot": "Londinium",
                    "raw_text": "...",
                    "date_from": 100,
                    "date_to": 200,
                    "persons": persons,
                },
            }
        ],
    }
    (tmp_path / "inscriptions_africa_proconsularis.geojson").write_text(json.dumps(africa))
    (tmp_path / "inscriptions_britannia.geojson").write_text(json.dumps(britannia))
    return tmp_path


def test_schema_created(tmp_path, sample_geojson_dir):
    db_path = tmp_path / "test.db"
    build(db_path=db_path, geojson_dir=sample_geojson_dir)
    conn = sqlite3.connect(db_path)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "inscriptions" in tables
    assert "flags" in tables
    conn.close()


def test_wal_mode_enabled(tmp_path, sample_geojson_dir):
    db_path = tmp_path / "test.db"
    build(db_path=db_path, geojson_dir=sample_geojson_dir)
    conn = sqlite3.connect(db_path)
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"
    conn.close()


def test_inscriptions_loaded(tmp_path, sample_geojson_dir):
    db_path = tmp_path / "test.db"
    build(db_path=db_path, geojson_dir=sample_geojson_dir)
    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM inscriptions").fetchone()[0]
    assert count == 3
    conn.close()


def test_upsert_preserves_overrides(tmp_path, sample_geojson_dir):
    """Re-running the build for a province must not wipe manual overrides."""
    db_path = tmp_path / "test.db"
    build(db_path=db_path, geojson_dir=sample_geojson_dir)

    # Manually set an override on one inscription
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE inscriptions SET overrides = ? WHERE edcs_id = ?",
        ('{"corrected": true}', "EDCS-00000001"),
    )
    conn.commit()
    conn.close()

    # Re-run build (simulates pipeline re-run for africa)
    build(db_path=db_path, geojson_dir=sample_geojson_dir)

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT overrides FROM inscriptions WHERE edcs_id = ?", ("EDCS-00000001",)
    ).fetchone()
    assert row[0] == '{"corrected": true}', "overrides must survive a pipeline re-run"
    conn.close()


def test_province_column_set(tmp_path, sample_geojson_dir):
    db_path = tmp_path / "test.db"
    build(db_path=db_path, geojson_dir=sample_geojson_dir)
    conn = sqlite3.connect(db_path)
    provinces = {r[0] for r in conn.execute("SELECT DISTINCT province FROM inscriptions").fetchall()}
    assert provinces == {"africa_proconsularis", "britannia"}
    conn.close()
