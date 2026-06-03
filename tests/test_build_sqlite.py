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
lat_lon_to_tile = build_sqlite.lat_lon_to_tile
AGGREGATE_ZOOM = build_sqlite.AGGREGATE_ZOOM
TILE_ZOOM = build_sqlite.TILE_ZOOM


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


@pytest.fixture
def sample_geojson_dir_with_enrichment(sample_geojson_dir):
    """Extend the basic fixture with an enrichment file for two of the three inscriptions."""
    enrichment = {
        "EDCS-00000001": {
            "translation": "To Marcus Tullius...",
            "summary": "Funerary inscription for a senator.",
        },
        "EDCS-00000002": {
            "translation": "To Lucius Brutus...",
            "summary": None,
        },
    }
    (sample_geojson_dir / "enrichment_africa_proconsularis.json").write_text(
        json.dumps(enrichment)
    )
    return sample_geojson_dir


def test_schema_created(tmp_path, sample_geojson_dir):
    db_path = tmp_path / "test.db"
    build(db_path=db_path, geojson_dir=sample_geojson_dir)
    conn = sqlite3.connect(db_path)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "inscriptions" in tables
    assert "flags" in tables
    assert "provinces" in tables
    assert "tile_aggregates" in tables
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


def test_enrichment_loaded(tmp_path, sample_geojson_dir_with_enrichment):
    db_path = tmp_path / "test.db"
    build(db_path=db_path, geojson_dir=sample_geojson_dir_with_enrichment)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = {
        r["edcs_id"]: r
        for r in conn.execute(
            "SELECT edcs_id, translation, summary FROM inscriptions"
        ).fetchall()
    }
    assert rows["EDCS-00000001"]["translation"] == "To Marcus Tullius..."
    assert rows["EDCS-00000001"]["summary"] == "Funerary inscription for a senator."
    assert rows["EDCS-00000002"]["translation"] == "To Lucius Brutus..."
    assert rows["EDCS-00000002"]["summary"] is None
    assert rows["EDCS-00000003"]["translation"] is None  # no enrichment for britannia
    conn.close()


def test_enrichment_survives_rebuild(tmp_path, sample_geojson_dir_with_enrichment):
    """Translation/summary survive a second build run (same enrichment re-applied)."""
    db_path = tmp_path / "test.db"
    build(db_path=db_path, geojson_dir=sample_geojson_dir_with_enrichment)
    build(db_path=db_path, geojson_dir=sample_geojson_dir_with_enrichment)
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT translation FROM inscriptions WHERE edcs_id = ?", ("EDCS-00000001",)
    ).fetchone()
    assert row[0] == "To Marcus Tullius..."
    conn.close()


def test_province_column_set(tmp_path, sample_geojson_dir):
    db_path = tmp_path / "test.db"
    build(db_path=db_path, geojson_dir=sample_geojson_dir)
    conn = sqlite3.connect(db_path)
    provinces = {r[0] for r in conn.execute("SELECT DISTINCT province FROM inscriptions").fetchall()}
    assert provinces == {"africa_proconsularis", "britannia"}
    conn.close()


def test_tile_coords_precomputed(tmp_path, sample_geojson_dir):
    db_path = tmp_path / "test.db"
    build(db_path=db_path, geojson_dir=sample_geojson_dir)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = {
        r["edcs_id"]: (r["tile_x"], r["tile_y"])
        for r in conn.execute("SELECT edcs_id, tile_x, tile_y FROM inscriptions").fetchall()
    }
    conn.close()
    assert rows["EDCS-00000001"] == lat_lon_to_tile(36.8, 10.2)
    assert rows["EDCS-00000002"] == lat_lon_to_tile(36.9, 10.3)
    assert rows["EDCS-00000003"] == lat_lon_to_tile(51.5, -0.1)


def test_tile_aggregates_precomputed(tmp_path, sample_geojson_dir):
    db_path = tmp_path / "test.db"
    build(db_path=db_path, geojson_dir=sample_geojson_dir)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    divisor = 2 ** (TILE_ZOOM - AGGREGATE_ZOOM)

    # Both africa inscriptions share the same z=AGGREGATE_ZOOM cell
    tx1, ty1 = lat_lon_to_tile(36.8, 10.2)
    tx2, ty2 = lat_lon_to_tile(36.9, 10.3)
    assert tx1 // divisor == tx2 // divisor
    assert ty1 // divisor == ty2 // divisor
    agg_x, agg_y = tx1 // divisor, ty1 // divisor

    row = conn.execute(
        "SELECT count FROM tile_aggregates WHERE zoom=? AND tile_x=? AND tile_y=?",
        (AGGREGATE_ZOOM, agg_x, agg_y),
    ).fetchone()
    assert row is not None
    assert row["count"] == 2  # both africa inscriptions

    # Britannia is in a different cell
    tx3, ty3 = lat_lon_to_tile(51.5, -0.1)
    brit_x, brit_y = tx3 // divisor, ty3 // divisor
    brit_row = conn.execute(
        "SELECT count FROM tile_aggregates WHERE zoom=? AND tile_x=? AND tile_y=?",
        (AGGREGATE_ZOOM, brit_x, brit_y),
    ).fetchone()
    assert brit_row is not None
    assert brit_row["count"] == 1
    conn.close()


def test_provinces_table_precomputed(tmp_path, sample_geojson_dir):
    db_path = tmp_path / "test.db"
    build(db_path=db_path, geojson_dir=sample_geojson_dir)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = {
        r["province"]: r
        for r in conn.execute("SELECT * FROM provinces").fetchall()
    }
    conn.close()
    assert set(rows.keys()) == {"africa_proconsularis", "britannia"}
    assert rows["africa_proconsularis"]["count"] == 2
    assert rows["britannia"]["count"] == 1
