"""Tests für die öffentliche Key-Anleitung /anleitung/keys."""
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


def test_keys_page_is_public(client):
    resp = client.get("/anleitung/keys", follow_redirects=False)
    assert resp.status_code == 200


def test_keys_page_explains_and_covers_both_providers(client):
    body = client.get("/anleitung/keys").text
    assert "Adzuna" in body
    assert "Jooble" in body
    assert "developer.adzuna.com" in body
    assert "jooble.org/api/about" in body
    assert "Aggregator" in body or "kostenlos" in body


def test_keys_page_references_screenshots(client):
    body = client.get("/anleitung/keys").text
    assert "/static/img/keys/" in body


def test_keys_page_ends_with_config_and_scan(client):
    body = client.get("/anleitung/keys").text
    assert "/plugin" in body
    assert "/bob:bob-scan" in body
