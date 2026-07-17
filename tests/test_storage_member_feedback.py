"""Tests für die member_feedback-Tabelle (Sag's-Bob-Widget)."""
import pytest

from jobscanner import storage


@pytest.fixture
def db(tmp_path):
    storage.init_db(tmp_path / "jobs.db")
    yield
    storage.close()


def test_create_member_feedback_returns_row_id(db):
    row_id = storage.create_member_feedback(1, "Der Score ist manchmal komisch.")
    assert row_id is not None
    assert row_id > 0


def test_create_member_feedback_persists_fields(db):
    row_id = storage.create_member_feedback(7, "Bug: Wizard hängt bei Schritt 3.")
    conn = storage._require_conn()
    row = conn.execute("SELECT * FROM member_feedback WHERE id = ?", (row_id,)).fetchone()
    assert row["user_id"] == 7
    assert row["text"] == "Bug: Wizard hängt bei Schritt 3."
    assert row["created_at"] is not None


def test_create_member_feedback_allows_multiple_rows_per_user(db):
    storage.create_member_feedback(3, "Erstes Feedback")
    storage.create_member_feedback(3, "Zweites Feedback")
    conn = storage._require_conn()
    count = conn.execute(
        "SELECT COUNT(*) AS n FROM member_feedback WHERE user_id = ?", (3,)).fetchone()["n"]
    assert count == 2
