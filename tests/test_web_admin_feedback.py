"""Tests für GET /admin/feedback (Owner-Übersicht über Member-Feedback)."""
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


def test_admin_feedback_requires_login(client):
    resp = client.get("/admin/feedback", follow_redirects=False)
    assert resp.status_code == 303


def test_admin_feedback_forbidden_for_member(client):
    client.post("/register", data={"email": "member@test.de", "password": "pw123456",
                                   "invite_code": "invite123", "consent": "on"})
    resp = client.get("/admin/feedback")
    assert resp.status_code == 403


def test_admin_feedback_lists_entries_for_owner(client):
    client.post("/login", data={"email": "owner@test.de", "password": "geheim123"})
    client.post("/api/feedback", json={"text": "Der Score ist manchmal komisch."})
    resp = client.get("/admin/feedback")
    assert resp.status_code == 200
    assert "Der Score ist manchmal komisch." in resp.text
    assert "owner@test.de" in resp.text


def test_admin_feedback_shows_empty_state(client):
    client.post("/login", data={"email": "owner@test.de", "password": "geheim123"})
    resp = client.get("/admin/feedback")
    assert resp.status_code == 200
    assert "Noch kein Feedback vorhanden." in resp.text
