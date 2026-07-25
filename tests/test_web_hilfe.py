"""Tests für den Hilfe-Hub /hilfe und den Sidebar-Umbau."""
import pytest
from fastapi.testclient import TestClient
from _csrf_client import CSRFTestClient

from jobscanner import storage
from jobscanner.web.app import create_app


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "geheim123")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@test.de")
    return create_app(db_path=tmp_path / "jobs.db")


@pytest.fixture
def member_client(app):
    storage.create_user("m@test.de", "pw", role="member")
    c = CSRFTestClient(app)
    c.post("/login", data={"email": "m@test.de", "password": "pw"})
    return c


def test_hilfe_is_public(app):
    resp = TestClient(app).get("/hilfe")
    assert resp.status_code == 200


def test_hilfe_has_three_cards(app):
    text = TestClient(app).get("/hilfe").text
    assert 'href="/anleitung"' in text
    assert 'href="/anleitung/scan"' in text
    assert 'href="/anleitung/keys"' in text
    assert "Einstieg, Zugang, Features" in text
    assert "Heim-IP-Scan einrichten" in text


def test_drawer_has_hilfe_instead_of_two_anleitung_links(member_client):
    text = member_client.get("/").text
    assert '<a class="drawer-item" href="/hilfe">' in text
    assert '<a class="drawer-item" href="/anleitung">' not in text
    assert '<a class="drawer-item" href="/anleitung/scan">' not in text
