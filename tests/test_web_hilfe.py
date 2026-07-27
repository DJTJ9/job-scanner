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


@pytest.fixture
def client(app):
    c = CSRFTestClient(app)
    c.post("/login", data={"email": "owner@test.de", "password": "geheim123"})
    return c


@pytest.fixture
def client_ohne_login(app):
    return CSRFTestClient(app)


def test_hilfe_is_public(app):
    resp = TestClient(app).get("/hilfe")
    assert resp.status_code == 200


def test_hilfe_has_three_scan_cards(app):
    text = TestClient(app).get("/hilfe").text
    assert 'href="/anleitung/scan"' in text
    assert 'href="/anleitung/keys"' in text
    assert 'href="/scan"' in text
    assert "Heim-IP-Scan einrichten" in text


def test_hilfe_center_sektionen(client):
    resp = client.get("/hilfe")
    assert resp.status_code == 200
    for anker in ["erste-schritte", "funktionen", "anleitung", "scannen",
                  "sicherheit", "faq"]:
        assert f'id="{anker}"' in resp.text
    assert "In 5 Minuten mit Bob verbunden" in resp.text   # Anleitungs-Inhalt
    assert "Wer bin ich?" in resp.text                     # Onboarding-Inhalt


def test_hilfe_public_ohne_login(client_ohne_login):
    resp = client_ohne_login.get("/hilfe")
    assert resp.status_code == 200


def test_anleitung_301(client_ohne_login):
    resp = client_ohne_login.get("/anleitung", follow_redirects=False)
    assert resp.status_code == 301
    assert resp.headers["location"] == "/hilfe#anleitung"


def test_onboarding_301(client_ohne_login):
    resp = client_ohne_login.get("/onboarding", follow_redirects=False)
    assert resp.status_code == 301
    assert resp.headers["location"] == "/hilfe#erste-schritte"


def test_drawer_has_hilfe_instead_of_two_anleitung_links(member_client):
    text = member_client.get("/").text
    assert '<a class="drawer-item" href="/hilfe">' in text
    assert '<a class="drawer-item" href="/anleitung">' not in text
    assert '<a class="drawer-item" href="/anleitung/scan">' not in text
