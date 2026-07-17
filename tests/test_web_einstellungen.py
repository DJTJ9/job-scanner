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


def test_password_post_renders_settings_success(member):
    resp = member.post("/account/passwort", data={
        "current_password": "pw", "new_password": "neupw1",
        "new_password_repeat": "neupw1"}, follow_redirects=False)
    assert resp.status_code == 200
    assert "geändert" in resp.text
    assert 'data-tab="profil"' in resp.text


def test_password_post_error_renders_settings(member):
    resp = member.post("/account/passwort", data={
        "current_password": "falsch", "new_password": "neupw1",
        "new_password_repeat": "neupw1"}, follow_redirects=False)
    assert resp.status_code == 400
    assert "falsch" in resp.text
    assert 'data-tab="profil"' in resp.text


def test_token_post_renders_settings_with_token(member):
    resp = member.post("/profiles/api-token", follow_redirects=False)
    assert resp.status_code == 200
    assert "bob_" in resp.text
    assert 'data-tab="token"' in resp.text


def test_startseite_has_no_token_panel(member):
    body = member.get("/").text
    assert "API-Token erzeugen" not in body


def test_password_get_redirects_to_settings_when_logged_in(member):
    resp = member.get("/account/passwort", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/einstellungen"
