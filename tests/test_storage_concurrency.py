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


class _FakeConn:
    def __init__(self):
        self.rollbacks = 0

    def rollback(self):
        self.rollbacks += 1


def test_retry_decorator_retries_and_rolls_back(monkeypatch):
    fake = _FakeConn()
    monkeypatch.setattr(storage, "_conn", fake)
    monkeypatch.setattr(storage.time, "sleep", lambda *_: None)
    attempts = {"n": 0}

    @storage._retry_on_locked
    def writer():
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise sqlite3.OperationalError("database is locked")
        return "ok"

    assert writer() == "ok"        # Erfolg trotz erstem Lock
    assert attempts["n"] == 2      # genau ein Retry
    assert fake.rollbacks == 1     # Rollback vor dem Retry


def test_retry_decorator_reraises_non_locked(monkeypatch):
    monkeypatch.setattr(storage, "_conn", _FakeConn())
    monkeypatch.setattr(storage.time, "sleep", lambda *_: None)

    @storage._retry_on_locked
    def writer():
        raise sqlite3.OperationalError("no such column: foo")

    with pytest.raises(sqlite3.OperationalError):
        writer()


def test_retry_decorator_gives_up_after_five(monkeypatch):
    monkeypatch.setattr(storage, "_conn", _FakeConn())
    monkeypatch.setattr(storage.time, "sleep", lambda *_: None)
    attempts = {"n": 0}

    @storage._retry_on_locked
    def writer():
        attempts["n"] += 1
        raise sqlite3.OperationalError("database is locked")

    with pytest.raises(sqlite3.OperationalError):
        writer()
    assert attempts["n"] == 5       # 5 Versuche, dann raise


def test_decorated_write_function_still_works_end_to_end(fresh_db):
    # create_user ist dekoriert und muss normal weiter funktionieren
    uid = storage.create_user("concurrency@test.de", "pw", "member")
    assert uid
    rows = fresh_db.execute(
        "SELECT COUNT(*) FROM users WHERE email = ?", ("concurrency@test.de",)
    ).fetchone()[0]
    assert rows == 1
