"""Tests für den Einmal-Backfill der is_ausland-Spalte (Zielraum DE/AT/NL)."""
import sqlite3

import pytest

from tools.backfill_is_ausland import backfill


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "jobs.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE jobs (fingerprint TEXT PRIMARY KEY, location TEXT, "
                 "is_ausland INTEGER DEFAULT 0)")
    conn.executemany("INSERT INTO jobs VALUES (?, ?, ?)", [
        ("us-zip", "New York, NY 10001", 0),   # Lücke: galt als deutsch
        ("nl", "Amsterdam, Netherlands", 1),   # neu Zielraum
        ("de", "Hamburg", 0),                  # unverändert
        ("us", "Los Angeles, CA", 1),          # unverändert
    ])
    conn.commit()
    conn.close()
    return path


def test_backfill_korrigiert_nur_abweichende_zeilen(db):
    geaendert = backfill(db)
    assert {(fp, alt, neu) for fp, _loc, alt, neu in geaendert} == {
        ("us-zip", 0, 1), ("nl", 1, 0)}
    conn = sqlite3.connect(db)
    werte = dict(conn.execute("SELECT fingerprint, is_ausland FROM jobs"))
    conn.close()
    assert werte == {"us-zip": 1, "nl": 0, "de": 0, "us": 1}


def test_backfill_dry_run_schreibt_nicht(db):
    geaendert = backfill(db, dry_run=True)
    assert len(geaendert) == 2
    conn = sqlite3.connect(db)
    werte = dict(conn.execute("SELECT fingerprint, is_ausland FROM jobs"))
    conn.close()
    assert werte == {"us-zip": 0, "nl": 1, "de": 0, "us": 1}


def test_backfill_ist_idempotent(db):
    backfill(db)
    assert backfill(db) == []
