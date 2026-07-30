"""Tests für die eigene Handbuch-Seite /hilfe/handbuch (UI-Refine D3)."""
import pytest
from fastapi.testclient import TestClient

from jobscanner.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "geheim123")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@test.de")
    return TestClient(create_app(db_path=tmp_path / "jobs.db"))


def test_handbuch_is_public(client):
    assert client.get("/hilfe/handbuch").status_code == 200


def test_handbuch_has_toc_and_sections(client):
    body = client.get("/hilfe/handbuch").text
    for anker in ("ueberblick", "profil", "jobs", "scannen", "konto"):
        assert f'id="{anker}"' in body
    assert "Handbuch" in body
    assert 'class="hb-toc"' in body


def test_handbuch_covers_core_commands(client):
    body = client.get("/hilfe/handbuch").text
    assert "/bob:bob-rescore" in body
    assert "/bob:bob-scan" in body


def test_handbuch_back_link_to_hilfe(client):
    body = client.get("/hilfe/handbuch").text
    assert 'href="/hilfe' in body
