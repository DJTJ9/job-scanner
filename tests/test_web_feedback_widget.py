"""Tests für POST /api/feedback (Sag's-Bob-Widget)."""
import pytest
from fastapi.testclient import TestClient
from _csrf_client import CSRFTestClient

from jobscanner import storage
from jobscanner.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "geheim123")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@test.de")
    monkeypatch.setenv("JOBSCANNER_INVITE_CODE", "invite123")
    app = create_app(db_path=tmp_path / "jobs.db")
    return CSRFTestClient(app)


def test_feedback_requires_login(client):
    resp = client.post("/api/feedback", json={"text": "Hallo Bob"})
    assert resp.status_code == 401


def test_feedback_valid_text_creates_row_and_returns_confirmation(client):
    client.post("/login", data={"email": "owner@test.de", "password": "geheim123"})
    resp = client.post("/api/feedback", json={"text": "Der Score ist manchmal komisch."})
    assert resp.status_code == 200
    assert resp.json()["message"] == "Bob hat's notiert. Danke!"
    conn = storage._require_conn()
    row = conn.execute("SELECT * FROM member_feedback ORDER BY id DESC LIMIT 1").fetchone()
    assert row["text"] == "Der Score ist manchmal komisch."


def test_feedback_records_correct_user_id(client):
    client.post("/register", data={"email": "member@test.de", "password": "pw123456",
                                   "invite_code": "invite123", "consent": "on"})
    uid = storage.get_user_by_email("member@test.de")["id"]
    client.post("/api/feedback", json={"text": "Feature-Wunsch: Dark Mode toggle"})
    conn = storage._require_conn()
    row = conn.execute("SELECT * FROM member_feedback ORDER BY id DESC LIMIT 1").fetchone()
    assert row["user_id"] == uid


def test_feedback_empty_text_rejected(client):
    client.post("/login", data={"email": "owner@test.de", "password": "geheim123"})
    resp = client.post("/api/feedback", json={"text": "   "})
    assert resp.status_code == 400
    conn = storage._require_conn()
    count = conn.execute("SELECT COUNT(*) AS n FROM member_feedback").fetchone()["n"]
    assert count == 0


def test_feedback_missing_text_field_rejected(client):
    client.post("/login", data={"email": "owner@test.de", "password": "geheim123"})
    resp = client.post("/api/feedback", json={})
    assert resp.status_code == 400
