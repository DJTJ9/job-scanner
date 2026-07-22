"""Tests für die Member-Einstellungen /einstellungen (Reiter Profil + API-Token)."""
import pytest
from fastapi.testclient import TestClient
from _csrf_client import CSRFTestClient

from jobscanner import storage
from jobscanner.web.app import create_app


@pytest.fixture
def member(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "geheim123")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@test.de")
    app = create_app(db_path=tmp_path / "jobs.db")
    storage.create_user("m@test.de", "pw", role="member")
    c = CSRFTestClient(app)
    c.post("/login", data={"email": "m@test.de", "password": "pw"})
    return c


def test_settings_requires_login(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "geheim123")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@test.de")
    app = create_app(db_path=tmp_path / "jobs.db")
    c = CSRFTestClient(app)
    resp = c.get("/einstellungen", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_settings_shows_email_and_both_tabs(member):
    body = member.get("/einstellungen").text
    assert "m@test.de" in body
    assert 'data-tab="profil"' in body
    assert 'data-tab="token"' in body


def test_settings_has_password_form(member):
    body = member.get("/einstellungen").text
    assert 'action="/account/passwort"' in body
    assert 'name="current_password"' in body
    assert 'name="new_password"' in body


def test_settings_has_token_button(member):
    body = member.get("/einstellungen").text
    assert 'action="/profiles/api-token"' in body
    assert "API-Token erzeugen" in body


def test_settings_has_bob_befehle_buttons(member):
    member.post("/profiles/api-token")
    body = member.get("/einstellungen").text
    assert "claude-cli://open?q=%2Fbob%3Abob-scan" in body
    assert "claude-cli://open?q=%2Fbob%3Abob-score" in body
    assert "/bob:bob-scan" in body
    assert "/bob:bob-score" in body


def test_settings_bob_befehle_have_copy_fallback(member):
    member.post("/profiles/api-token")
    body = member.get("/einstellungen").text
    assert body.count('class="copy-btn"') >= 2
    assert 'data-copy="/bob:bob-scan"' in body
    assert 'data-copy="/bob:bob-score"' in body


def test_password_post_renders_settings_success(member):
    resp = member.post("/account/passwort", data={
        "current_password": "pw", "new_password": "neupw1",
        "new_password_repeat": "neupw1"}, follow_redirects=False)
    assert resp.status_code == 200
    assert "geändert" in resp.text
    assert 'data-tab="profil"' in resp.text


def test_password_post_error_renders_settings(member):
    resp = member.post("/account/passwort", data={
        "current_password": "falsch", "new_password": "neupw1",
        "new_password_repeat": "neupw1"}, follow_redirects=False)
    assert resp.status_code == 400
    assert "falsch" in resp.text
    assert 'data-tab="profil"' in resp.text


def test_token_post_renders_settings_with_token(member):
    resp = member.post("/profiles/api-token", follow_redirects=False)
    assert resp.status_code == 200
    assert "bob_" in resp.text
    assert 'data-tab="token"' in resp.text


def test_startseite_has_no_token_panel(member):
    body = member.get("/").text
    assert "API-Token erzeugen" not in body


def test_password_get_redirects_to_settings_when_logged_in(member):
    resp = member.get("/account/passwort", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/einstellungen"


def test_settings_has_four_bob_command_cards(member):
    body = member.get("/einstellungen").text
    for cmd in ("bob-scan", "bob-score", "bob-learn", "bob-profil"):
        assert f'data-copy="/bob:{cmd}"' in body


def test_settings_without_token_shows_abo_hint_instead_of_deeplink(member):
    body = member.get("/einstellungen").text
    assert "Braucht eigenes Claude-Abo" in body
    assert "claude-cli://open" not in body


def test_settings_with_token_shows_deeplinks(member):
    member.post("/profiles/api-token")
    body = member.get("/einstellungen").text
    assert "claude-cli://open?q=%2Fbob%3Abob-profil" in body
    assert "Braucht eigenes Claude-Abo" not in body


def test_spar_modus_form_renders_with_defaults(member):
    body = member.get("/einstellungen").text
    assert 'action="/einstellungen/spar-modus"' in body
    assert 'name="modus"' in body
    assert 'name="neighbor_roles"' in body


def test_spar_modus_post_persists_to_profile(member):
    storage.create_profile("M", {}, user_id=storage.get_user_by_email("m@test.de")["id"])
    resp = member.post("/einstellungen/spar-modus", data={
        "modus": "sparsam", "max_jobs": "25"}, follow_redirects=False)
    assert resp.status_code == 303
    uid = storage.get_user_by_email("m@test.de")["id"]
    prof = storage.list_profiles(user_id=uid)[0]
    assert storage.get_spar_modus(prof["data"]) == {"max_jobs": 25, "neighbor_roles": False,
                                                    "locations": [], "languages": ["de"]}


def test_spar_modus_post_unbegrenzt_resets_limit(member):
    storage.create_profile("M2", {}, user_id=storage.get_user_by_email("m@test.de")["id"])
    member.post("/einstellungen/spar-modus", data={
        "modus": "unbegrenzt", "max_jobs": "25", "neighbor_roles": "on"})
    uid = storage.get_user_by_email("m@test.de")["id"]
    prof = storage.list_profiles(user_id=uid)[0]
    assert storage.get_spar_modus(prof["data"]) == {"max_jobs": None, "neighbor_roles": True,
                                                    "locations": [], "languages": ["de"]}


def test_spar_modus_post_persists_location_language(member):
    storage.create_profile("M", {}, user_id=storage.get_user_by_email("m@test.de")["id"])
    member.post("/einstellungen/spar-modus", data={
        "modus": "sparsam", "max_jobs": "25",
        "locations": "Berlin, Remote", "lang_de": "on"})
    uid = storage.get_user_by_email("m@test.de")["id"]
    spar = storage.get_spar_modus(storage.list_profiles(user_id=uid)[0]["data"])
    assert spar["locations"] == ["Berlin", "Remote"]
    assert spar["languages"] == ["de"]


def test_spar_modus_form_renders_location_language_controls(member):
    r = member.get("/einstellungen")
    assert 'name="locations"' in r.text
    assert 'name="lang_de"' in r.text
    assert 'name="lang_en"' in r.text
