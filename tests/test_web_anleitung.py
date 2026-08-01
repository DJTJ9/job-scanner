"""Tests für die Member-Anleitung — jetzt Sektion #anleitung im Hilfe-Center /hilfe."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jobscanner.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "geheim123")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@test.de")
    app = create_app(db_path=tmp_path / "jobs.db")
    return TestClient(app)


def test_anleitung_redirects_301_to_hilfe(client):
    resp = client.get("/anleitung", follow_redirects=False)
    assert resp.status_code == 301
    assert resp.headers["location"] == "/hilfe#erste-schritte"


def test_anleitung_has_all_key_commands(client):
    # Die Claude-Code-Installationsbefehle stehen nicht mehr hier: Schritt
    # "Claude Code installieren" ist aus dem Hilfe-Center entfallen, die
    # Langfassung steht in /anleitung/vollstaendig (3.1).
    body = client.get("/hilfe").text
    assert "/plugin marketplace add DJTJ9/bob-member-kit" in body
    assert "/plugin install bob@bob-kit" in body
    assert "/bob:bob-rescore" in body
    assert "/bob:bob-scan" in body


def test_anleitung_embeds_real_screenshots(client):
    body = client.get("/hilfe").text
    assert "/static/img/anleitung/01-register.png" in body
    assert "/static/img/anleitung/03-token.png" in body


def test_anleitung_links_register(client):
    body = client.get("/hilfe").text
    assert 'href="/register"' in body


def test_anleitung_mentions_no_zip_and_no_bob_setup(client):
    body = client.get("/hilfe").text.lower()
    assert "zip" not in body
    assert "/bob-setup" not in body


def test_anleitung_links_to_keys_guide(client):
    body = client.get("/hilfe").text
    assert 'href="/anleitung/keys"' in body


def test_anleitung_referenced_screenshots_exist_on_disk():
    base = Path("jobscanner/web/static/img/anleitung")
    assert (base / "01-register.png").exists()
    assert (base / "03-token.png").exists()
