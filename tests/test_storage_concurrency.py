import sqlite3

import pytest

from jobscanner import storage


@pytest.fixture
def fresh_db(tmp_path):
    storage.init_db(tmp_path / "concurrency.db")
    yield storage._require_conn()
    storage.close()


def test_wal_and_busy_timeout_and_synchronous(fresh_db):
    conn = fresh_db
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    # synchronous: NORMAL == 1
    assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1


def test_secondary_indices_exist(fresh_db):
    names = {
        r[0]
        for r in fresh_db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        )
    }
    assert {
        "idx_jobs_extraction_status",
        "idx_jobs_status",
        "idx_jobs_category",
    } <= names


@pytest.mark.parametrize(
    "col,idx",
    [
        ("extraction_status", "idx_jobs_extraction_status"),
        ("status", "idx_jobs_status"),
        ("category", "idx_jobs_category"),
    ],
)
def test_filter_query_uses_index(fresh_db, col, idx):
    plan = fresh_db.execute(
        f"EXPLAIN QUERY PLAN SELECT * FROM jobs WHERE {col} = ?", ("x",)
    ).fetchall()
    detail = " ".join(str(r[-1]) for r in plan)
    assert idx in detail, f"expected {idx} in plan, got: {detail}"
