"""Tests für Owner-only Metriken-Dashboard (/dashboard/{id}/metriken)."""
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
    c = CSRFTestClient(app)
    c.post("/login", data={"email": "owner@test.de", "password": "geheim123"})
    return c, app


def _owner_profile_id(client):
    return storage.list_profiles()[0]["id"]


def test_metrics_page_shows_stat_tiles(client):
    c, _ = client
    pid = _owner_profile_id(c)
    storage.log_event("onboarding_start")
    storage.log_event("profil_erstellt")
    resp = c.get(f"/dashboard/{pid}/metriken")
    assert resp.status_code == 200
    assert "Aktive Member 7T" in resp.text
    assert "Onboarding-Completion" in resp.text
    assert "100%" in resp.text


def test_metrics_page_shows_funnel_and_ping_verlauf(client):
    c, _ = client
    pid = _owner_profile_id(c)
    storage.log_event("onboarding_start")
    resp = c.get(f"/dashboard/{pid}/metriken")
    assert "Onboarding-Start" in resp.text
    assert "Ping-Verlauf" in resp.text
    assert 'class="ping-bar ping"' in resp.text


def test_metrics_page_forbidden_for_member(client):
    _, app = client
    member_client = CSRFTestClient(app)
    member_client.post("/register", data={"email": "m@test.de", "password": "pw123456",
                                          "invite_code": "invite123"})
    uid = storage.get_user_by_email("m@test.de")["id"]
    pid = storage.create_profile("MemberP", {}, user_id=uid)
    resp = member_client.get(f"/dashboard/{pid}/metriken")
    assert resp.status_code == 403


def test_dashboard_owner_sees_metriken_tab_link(client):
    c, _ = client
    pid = _owner_profile_id(c)
    resp = c.get(f"/dashboard/{pid}")
    assert f'href="/dashboard/{pid}/metriken"' in resp.text
