"""Member-Onboarding-Anleitung: profile_exists-Flag, Buttons/Partials, CSS/JS-Reuse."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jobscanner import storage
from jobscanner.web.app import create_app


@pytest.fixture
def owner_client(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "geheim123")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@test.de")
    app = create_app(db_path=tmp_path / "jobs.db")
    c = TestClient(app)
    c.post("/login", data={"email": "owner@test.de", "password": "geheim123"})
    return c


@pytest.fixture
def member_client(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "geheim123")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@test.de")
    app = create_app(db_path=tmp_path / "jobs.db")
    storage.create_user("member@test.de", "pw", role="member")
    c = TestClient(app)
    c.post("/login", data={"email": "member@test.de", "password": "pw"})
    return c


def test_profile_exists_true_for_owner_with_migrated_profile(owner_client):
    resp = owner_client.get("/")
    assert 'data-profile-exists="true"' in resp.text


def test_profile_exists_false_for_member_without_profile(member_client):
    resp = member_client.get("/")
    assert 'data-profile-exists="false"' in resp.text


def test_hero_buttons_render_when_no_profile(member_client):
    resp = member_client.get("/")
    assert "onboarding-hero" in resp.text
    assert 'data-onboarding-open="onboarding-bot"' in resp.text
    assert 'data-onboarding-open="onboarding-wizard"' in resp.text
    assert "Wer bin ich und was kann ich?" in resp.text
    assert "Wer bist du und was möchtest du finden?" in resp.text


def test_corner_icons_render_when_profile_exists_not_hero(owner_client):
    resp = owner_client.get("/")
    assert "onboarding-corner" in resp.text
    assert "onboarding-hero" not in resp.text


def test_onboarding_panels_hidden_by_default_and_wizard_links_to_new(member_client):
    resp = member_client.get("/")
    assert 'id="onboarding-bot" class="panel onboarding-panel panel-hidden"' in resp.text
    assert 'id="onboarding-wizard" class="panel onboarding-panel panel-hidden"' in resp.text
    assert 'href="/wizard/new"' in resp.text
    assert 'data-onboarding-close="onboarding-bot"' in resp.text
    assert 'data-onboarding-close="onboarding-wizard"' in resp.text


def test_onboarding_css_classes_present_and_reuse_theme():
    css = Path("jobscanner/web/static/style.css").read_text()
    for cls in (".onboarding-hero", ".onboarding-header", ".onboarding-corner",
                ".onboarding-icon-btn", ".onboarding-panel", ".onboarding-avatar-wrap"):
        assert cls in css
    assert "var(--signal)" in css.split(".onboarding-icon-btn")[1].split("}")[0]


def test_onboarding_css_reuses_ping_keyframes_only():
    css = Path("jobscanner/web/static/style.css").read_text()
    assert css.count("@keyframes") == 1   # nur ping-pulse — keine neue Animation


def test_app_js_has_onboarding_toggle_snippet():
    js = Path("jobscanner/web/static/app.js").read_text()
    assert 'data-onboarding-open' in js
    assert 'data-onboarding-close' in js
    assert 'panel-hidden' in js
