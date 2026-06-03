import json
import os
import sqlite3
import pytest

_SAMPLE_PERSONS = json.dumps([{
    "praenomen": "Marcus", "nomen": "Tullius", "cognomen": "Cicero",
    "gender": "male", "status": "senator",
    "cluster_id": 1, "cluster_size": 2, "cluster_confidence": "high",
}])

# Pre-computed tile coords at z=10 for the three test inscriptions:
#   (36.8, 10.2)  → (541, 399)
#   (36.9, 10.3)  → (541, 398)
#   (51.5, -0.1)  → (511, 340)
_ROWS = [
    ("EDCS-00000001", "africa_proconsularis",
     36.8, 10.2, "Carthago", "M. Tullio...", -50, 50,
     _SAMPLE_PERSONS, None, None, None, 541, 399, "2026-01-01T00:00:00+00:00"),
    ("EDCS-00000002", "africa_proconsularis",
     36.9, 10.3, "Carthago", "L. Bruto...", 0, 100,
     _SAMPLE_PERSONS, None, "Translation for inscription 2", "Summary for inscription 2",
     541, 398, "2026-01-01T00:00:00+00:00"),
    ("EDCS-00000003", "britannia",
     51.5, -0.1, "Londinium", "...", 100, 200,
     _SAMPLE_PERSONS, None, None, None, 511, 340, "2026-01-01T00:00:00+00:00"),
]


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    """Populate a temp SQLite db and point server.db at it."""
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("ROMAN_NAMES_DB", str(db_path))

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE inscriptions (
            edcs_id TEXT PRIMARY KEY, province TEXT NOT NULL,
            lat REAL NOT NULL, lon REAL NOT NULL,
            findspot TEXT, raw_text TEXT,
            date_from INTEGER, date_to INTEGER,
            persons TEXT NOT NULL, overrides TEXT,
            translation TEXT, summary TEXT,
            tile_x INTEGER NOT NULL DEFAULT 0,
            tile_y INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE tile_aggregates (
            zoom INTEGER NOT NULL, tile_x INTEGER NOT NULL, tile_y INTEGER NOT NULL,
            lat REAL NOT NULL, lon REAL NOT NULL, count INTEGER NOT NULL,
            PRIMARY KEY (zoom, tile_x, tile_y)
        );
        CREATE TABLE provinces (
            province TEXT PRIMARY KEY,
            lat REAL NOT NULL, lon REAL NOT NULL,
            count INTEGER NOT NULL
        );
        CREATE TABLE flags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            edcs_id TEXT NOT NULL, category TEXT NOT NULL,
            comment TEXT, email TEXT, created_at TEXT NOT NULL
        );
        CREATE INDEX idx_inscriptions_tile ON inscriptions (tile_x, tile_y);
    """)
    conn.executemany(
        "INSERT INTO inscriptions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        _ROWS,
    )
    # z=7 aggregate cells: EDCS-1,2 → (67,49); EDCS-3 → (63,42)
    conn.executemany(
        "INSERT INTO tile_aggregates VALUES (?,?,?,?,?,?)",
        [
            (7, 67, 49, 36.85, 10.25, 2),
            (7, 63, 42, 51.5, -0.1,  1),
        ],
    )
    conn.executemany(
        "INSERT INTO provinces VALUES (?,?,?,?)",
        [
            ("africa_proconsularis", 36.85, 10.25, 2),
            ("britannia", 51.5, -0.1, 1),
        ],
    )
    conn.commit()
    conn.close()
    return db_path
