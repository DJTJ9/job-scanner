"""Tests für Email/Passwort-Login, Logout und Session-Guard."""
import pytest
from fastapi.testclient import TestClient
from _csrf_client import CSRFTestClient

from jobscanner.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "geheim123")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@test.de")
    app = create_app(db_path=tmp_path / "jobs.db")
    return CSRFTestClient(app)


def test_root_shows_landing_when_unauthenticated(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 200
    assert 'href="/login"' in resp.text   # Landing mit Anmelden-CTA statt Redirect


def test_login_wrong_password_rejected(client):
    resp = client.post("/login", data={"email": "owner@test.de", "password": "falsch"})
    assert resp.status_code == 401
    assert "Falsche Zugangsdaten" in resp.text


def test_login_correct_sets_session_and_redirects(client):
    resp = client.post("/login", data={"email": "owner@test.de", "password": "geheim123"},
                       follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    resp2 = client.get("/", follow_redirects=False)
    assert resp2.status_code == 200


def test_owner_seeded_with_owner_role(client):
    from jobscanner import storage
    assert storage.get_user_by_email("owner@test.de")["role"] == "owner"


def test_logout_clears_session(client):
    client.post("/login", data={"email": "owner@test.de", "password": "geheim123"})
    client.get("/logout")
    resp = client.get("/jobs", follow_redirects=False)   # login-pflichtige Seite
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"
