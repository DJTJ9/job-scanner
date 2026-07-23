"""Tests für die öffentliche Scan-Anleitung /anleitung/scan."""
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


def test_scan_anleitung_is_public(client):
    resp = client.get("/anleitung/scan", follow_redirects=False)
    assert resp.status_code == 200


def test_scan_anleitung_has_scan_command(client):
    body = client.get("/anleitung/scan").text
    assert "/bob:bob-scan" in body


def test_scan_anleitung_explains_scan_vs_score(client):
    body = client.get("/anleitung/scan").text
    assert "/bob:bob-score" in body


def test_scan_anleitung_links_keys_guide(client):
    body = client.get("/anleitung/scan").text
    assert 'href="/anleitung/keys"' in body


def test_scan_anleitung_links_back_to_main_guide(client):
    body = client.get("/anleitung/scan").text
    assert 'href="/anleitung"' in body


def test_scan_anleitung_mentions_functions_without_abo(client):
    body = client.get("/anleitung/scan").text.lower()
    assert "ohne abo" in body


def test_scan_anleitung_does_not_render_slogan_as_text(client):
    # Werbespruch steckt im Bild, nicht als HTML-Text
    body = client.get("/anleitung/scan").text
    assert "größten Job eures Lebens" not in body


def test_scan_background_image_exists_on_disk():
    img = Path("jobscanner/web/static/img/Bob-Scan-Anleitung-Background.png")
    assert img.exists()


def test_main_anleitung_links_to_scan_guide(client):
    body = client.get("/anleitung").text
    assert 'href="/anleitung/scan"' in body
