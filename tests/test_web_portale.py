"""Tests für /portale — Portal-Pre-Check-Tool Web-Routen."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from jobscanner import storage
from jobscanner.web.app import create_app


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "ownerpw")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@test.de")
    return create_app(db_path=tmp_path / "jobs.db")


def _login(client, email="owner@test.de", pw="ownerpw"):
    return client.post("/login", data={"email": email, "password": pw})


def test_portale_requires_login(app):
    c = TestClient(app)
    resp = c.get("/portale", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_pruefen_compatible_shows_success_and_activate_button(app):
    c = TestClient(app)
    _login(c)
    with patch("jobscanner.web.app.precheck.precheck_portal",
              return_value={"rendered": True, "blocked": False, "structured": True,
                           "compatible": True}):
        resp = c.post("/portale/pruefen",
                      data={"url": "https://foo.de/karriere", "typ": "career_page"})
    assert resp.status_code == 200
    assert "Flachwasser" in resp.text
    assert "Zur Suchliste hinzufügen" in resp.text
    row = storage.list_custom_portals()[0]
    assert row["status"] == "compatible"


def test_pruefen_incompatible_shows_firecrawl_optin(app):
    c = TestClient(app)
    _login(c)
    with patch("jobscanner.web.app.precheck.precheck_portal",
              return_value={"rendered": True, "blocked": True, "structured": False,
                           "compatible": False}):
        resp = c.post("/portale/pruefen",
                      data={"url": "https://bar.de", "typ": "career_page"})
    assert resp.status_code == 200
    assert "Riff erkannt" in resp.text
    assert "Trotzdem mit Firecrawl aufnehmen" in resp.text


def test_aktivieren_sets_active_and_redirects(app):
    c = TestClient(app)
    _login(c)
    uid = storage.get_user_by_email("owner@test.de")["id"]
    pid = storage.create_custom_portal("https://foo.de", "career_page", uid)
    storage.save_check_result(pid, {"compatible": True})
    resp = c.post(f"/portale/aktivieren/{pid}", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/portale"
    assert storage.get_custom_portal(pid)["status"] == "active"


def test_portale_list_shows_all_users_entries(app):
    c = TestClient(app)
    _login(c)
    uid = storage.get_user_by_email("owner@test.de")["id"]
    storage.create_custom_portal("https://a.de", "career_page", uid)
    resp = c.get("/portale")
    assert "a.de" in resp.text
