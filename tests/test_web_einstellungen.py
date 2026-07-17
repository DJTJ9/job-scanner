"""Tests für die Member-Einstellungen /einstellungen (Reiter Profil + API-Token)."""
import pytest
from fastapi.testclient import TestClient

from jobscanner import storage
from jobscanner.web.app import create_app


@pytest.fixture
def member(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "geheim123")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@test.de")
    app = create_app(db_path=tmp_path / "jobs.db")
    storage.create_user("m@test.de", "pw", role="member")
    c = TestClient(app)
    c.post("/login", data={"email": "m@test.de", "password": "pw"})
    return c


def test_settings_requires_login(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "geheim123")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@test.de")
    app = create_app(db_path=tmp_path / "jobs.db")
    c = TestClient(app)
    resp = c.get("/einstellungen", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_settings_shows_email_and_both_tabs(member):
    body = member.get("/einstellungen").text
    assert "m@test.de" in body
    assert 'data-tab="profil"' in body
    assert 'data-tab="token"' in body


def test_settings_has_password_form(member):
    body = member.get("/einstellungen").text
    assert 'action="/account/passwort"' in body
    assert 'name="current_password"' in body
    assert 'name="new_password"' in body


def test_settings_has_token_button(member):
    body = member.get("/einstellungen").text
    assert 'action="/profiles/api-token"' in body
    assert "API-Token erzeugen" in body
