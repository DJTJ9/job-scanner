"""Tests für die öffentliche Landeseite /mitmachen (Kommilitonen-Onboarding)."""
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


def test_mitmachen_is_public(client):
    resp = client.get("/mitmachen", follow_redirects=False)
    assert resp.status_code == 200


def test_mitmachen_has_both_plugin_commands(client):
    body = client.get("/mitmachen").text
    assert "/plugin marketplace add DJTJ9/bob-member-kit" in body
    assert "/plugin install bob@bob-kit" in body


def test_mitmachen_links_register_and_github(client):
    body = client.get("/mitmachen").text
    assert 'href="/register"' in body
    assert "github.com/DJTJ9/job-scanner" in body


def test_mitmachen_names_the_namespaced_score_command(client):
    body = client.get("/mitmachen").text
    assert "/bob:bob-score" in body


def test_mitmachen_has_install_command_and_four_stations(client):
    body = client.get("/mitmachen").text
    assert "irm https://claude.ai/install.ps1 | iex" in body
    assert body.count('class="station"') == 4


def test_mitmachen_mentions_no_zip_and_no_bob_setup(client):
    body = client.get("/mitmachen").text.lower()
    assert "zip" not in body
    assert "/bob-setup" not in body


def test_mitmachen_renders_logged_out_without_drawer_or_feedback(client):
    body = client.get("/mitmachen").text
    assert "drawer-toggle" not in body
    assert "feedback-fab" not in body


def test_mitmachen_shows_login_link_when_logged_out(client):
    body = client.get("/mitmachen").text
    assert 'href="/login"' in body


def test_footer_has_mitmachen_and_github_links(client):
    body = client.get("/mitmachen").text
    assert 'href="/mitmachen"' in body
    assert "github.com/DJTJ9/job-scanner" in body
