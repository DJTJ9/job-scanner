"""Tests für die öffentliche Member-Anleitung /anleitung."""
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


def test_anleitung_is_public(client):
    resp = client.get("/anleitung", follow_redirects=False)
    assert resp.status_code == 200


def test_anleitung_has_all_key_commands(client):
    body = client.get("/anleitung").text
    assert "irm https://claude.ai/install.ps1 | iex" in body
    assert "curl -fsSL https://claude.ai/install.sh | bash" in body
    assert "/plugin marketplace add DJTJ9/bob-member-kit" in body
    assert "/plugin install bob@bob-kit" in body
    assert "/bob:bob-score" in body
    assert "/bob:bob-scan" in body


def test_anleitung_embeds_real_screenshots(client):
    body = client.get("/anleitung").text
    assert "/static/img/anleitung/01-register.png" in body
    assert "/static/img/anleitung/03-token.png" in body


def test_anleitung_links_register(client):
    body = client.get("/anleitung").text
    assert 'href="/register"' in body


def test_anleitung_mentions_no_zip_and_no_bob_setup(client):
    body = client.get("/anleitung").text.lower()
    assert "zip" not in body
    assert "/bob-setup" not in body


def test_anleitung_links_to_keys_guide(client):
    body = client.get("/anleitung").text
    assert 'href="/anleitung/keys"' in body


def test_anleitung_referenced_screenshots_exist_on_disk():
    base = Path("jobscanner/web/static/img/anleitung")
    assert (base / "01-register.png").exists()
    assert (base / "03-token.png").exists()
