"""Tests für Login/Logout/Session-Guard."""
import pytest
from fastapi.testclient import TestClient

from jobscanner.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "geheim123")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    app = create_app(db_path=tmp_path / "jobs.db")
    return TestClient(app)


def test_root_redirects_to_login_when_unauthenticated(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_login_wrong_password_rejected(client):
    resp = client.post("/login", data={"password": "falsch"})
    assert resp.status_code == 401
    assert "Falsches Passwort" in resp.text


def test_login_correct_password_sets_session_and_redirects(client):
    resp = client.post("/login", data={"password": "geheim123"}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    resp2 = client.get("/", follow_redirects=False)
    assert resp2.status_code == 200


def test_logout_clears_session(client):
    client.post("/login", data={"password": "geheim123"})
    client.get("/logout")
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 303
