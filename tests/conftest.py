import json
import os
import sqlite3
import pytest

_SAMPLE_PERSONS = json.dumps([{
    "praenomen": "Marcus", "nomen": "Tullius", "cognomen": "Cicero",
    "gender": "male", "status": "senator",
    "cluster_id": 1, "cluster_size": 2, "cluster_confidence": "high",
}])


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
            updated_at TEXT NOT NULL
        );
        CREATE TABLE flags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            edcs_id TEXT NOT NULL, category TEXT NOT NULL,
            comment TEXT, email TEXT, created_at TEXT NOT NULL
        );
        CREATE INDEX idx_lat_lon ON inscriptions (lat, lon);
    """)
    conn.executemany(
        "INSERT INTO inscriptions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("EDCS-00000001", "africa_proconsularis",
             36.8, 10.2, "Carthago", "M. Tullio...", -50, 50,
             _SAMPLE_PERSONS, None, "2026-01-01T00:00:00+00:00"),
            ("EDCS-00000002", "africa_proconsularis",
             36.9, 10.3, "Carthago", "L. Bruto...", 0, 100,
             _SAMPLE_PERSONS, None, "2026-01-01T00:00:00+00:00"),
            ("EDCS-00000003", "britannia",
             51.5, -0.1, "Londinium", "...", 100, 200,
             _SAMPLE_PERSONS, None, "2026-01-01T00:00:00+00:00"),
        ],
    )
    conn.commit()
    conn.close()
    return db_path
