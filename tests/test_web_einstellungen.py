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


def test_settings_shows_email_and_four_tabs(member):
    body = member.get("/einstellungen").text
    assert "m@test.de" in body
    for slug in ("konto", "anbindungen", "suche", "notify"):
        assert f'data-tab="{slug}"' in body
    assert 'data-tab="profil"' not in body
    assert 'data-tab="token"' not in body
    assert 'data-tab="firecrawl"' not in body


def test_konto_tab_contains_email_export_delete(member):
    body = member.get("/einstellungen?tab=konto").text
    assert 'action="/account/email"' in body
    assert 'href="/account/export"' in body
    assert 'action="/account/loeschen"' in body
    assert "Gefahrenzone" in body


def test_anbindungen_tab_contains_token_firecrawl_agg_forms(member):
    body = member.get("/einstellungen?tab=anbindungen").text
    assert 'action="/profiles/api-token"' in body
    assert 'action="/einstellungen/firecrawl"' in body
    assert 'action="/einstellungen/adzuna"' in body
    assert 'action="/einstellungen/jooble"' in body


def test_account_email_get_redirects_to_konto_tab(member):
    resp = member.get("/account/email", follow_redirects=False)
    assert resp.status_code == 301
    assert resp.headers["location"] == "/einstellungen?tab=konto"


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
    assert "claude-cli://open?q=%2Fbob%3Abob-rescore" in body
    assert "/bob:bob-scan" in body
    assert "/bob:bob-rescore" in body


def test_settings_bob_befehle_have_copy_fallback(member):
    member.post("/profiles/api-token")
    body = member.get("/einstellungen").text
    assert body.count('class="copy-btn"') >= 2
    assert 'data-copy="/bob:bob-scan"' in body
    assert 'data-copy="/bob:bob-rescore"' in body


def test_password_post_renders_settings_success(member):
    resp = member.post("/account/passwort", data={
        "current_password": "pw", "new_password": "neupw1",
        "new_password_repeat": "neupw1"}, follow_redirects=False)
    assert resp.status_code == 200
    assert "geändert" in resp.text
    assert 'data-tab="konto"' in resp.text


def test_password_post_error_renders_settings(member):
    resp = member.post("/account/passwort", data={
        "current_password": "falsch", "new_password": "neupw1",
        "new_password_repeat": "neupw1"}, follow_redirects=False)
    assert resp.status_code == 400
    assert "falsch" in resp.text
    assert 'data-tab="konto"' in resp.text


def test_token_post_renders_settings_with_token(member):
    resp = member.post("/profiles/api-token", follow_redirects=False)
    assert resp.status_code == 200
    assert "bob_" in resp.text
    assert 'data-tab="anbindungen"' in resp.text


def test_startseite_has_no_token_panel(member):
    body = member.get("/").text
    assert "API-Token erzeugen" not in body


def test_password_get_redirects_to_settings_when_logged_in(member):
    resp = member.get("/account/passwort", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/einstellungen"


def test_settings_has_four_bob_command_cards(member):
    body = member.get("/einstellungen").text
    for cmd in ("bob-scan", "bob-rescore", "bob-learn", "bob-profil"):
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


def test_settings_shows_scan_portal_checkboxes_default_checked(member):
    body = member.get("/einstellungen").text
    assert 'name="portal_stepstone" checked' in body
    assert 'name="portal_indeed" checked' in body


def test_scan_portals_submit_persists_selection(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "geheim123")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@test.de")
    app = create_app(db_path=tmp_path / "jobs.db")
    uid = storage.create_user("p@test.de", "pw", role="member")
    storage.create_profile("P", {}, user_id=uid)
    c = CSRFTestClient(app)
    c.post("/login", data={"email": "p@test.de", "password": "pw"})

    resp = c.post("/einstellungen/scan-portale",
                  data={"portal_stepstone": "on"}, follow_redirects=False)
    assert resp.status_code == 303
    profile = storage.list_profiles(user_id=uid)[0]
    assert storage.get_scan_portals(profile["data"]) == ["stepstone"]

    # Beide abgewählt = bewusstes Opt-out, bleibt leer (kein Default-Rückfall).
    c.post("/einstellungen/scan-portale", data={}, follow_redirects=False)
    profile = storage.list_profiles(user_id=uid)[0]
    assert storage.get_scan_portals(profile["data"]) == []


def _activate_portal(uid, url="https://jobs.example.com"):
    pid = storage.create_custom_portal(url, "portal", uid,
                                       search_url_template=url + "/s?q={query}",
                                       detail_url_pattern=r"jobs\.example\.com/job/")
    storage.save_check_result(pid, {"compatible": True})
    storage.activate_custom_portal(pid)
    return pid


def test_settings_renders_active_custom_portal_checkbox(member):
    uid = storage.get_user_by_email("m@test.de")["id"]
    pid = _activate_portal(uid)
    body = member.get("/einstellungen").text
    assert f'name="portal_custom_{pid}"' in body
    assert "jobs.example.com" in body


def test_scan_portals_submit_persists_custom_selection(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "geheim123")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@test.de")
    app = create_app(db_path=tmp_path / "jobs.db")
    uid = storage.create_user("p@test.de", "pw", role="member")
    storage.create_profile("P", {}, user_id=uid)
    pid = _activate_portal(uid)
    c = CSRFTestClient(app)
    c.post("/login", data={"email": "p@test.de", "password": "pw"})

    resp = c.post("/einstellungen/scan-portale",
                  data={"portal_indeed": "on", f"portal_custom_{pid}": "on"},
                  follow_redirects=False)
    assert resp.status_code == 303
    profile = storage.list_profiles(user_id=uid)[0]
    assert storage.get_scan_portals(profile["data"]) == ["indeed", f"custom:{pid}"]


def test_stille_forms_tragen_confirm_save(member):
    body = member.get("/einstellungen").text
    assert 'action="/einstellungen/spar-modus" data-confirm-save' in body
    assert 'action="/einstellungen/scan-portale" data-confirm-save' in body
    assert 'action="/einstellungen/notify" data-confirm-save' in body


def test_passwort_form_hat_kein_confirm_save(member):
    body = member.get("/einstellungen").text
    assert 'action="/account/passwort" data-confirm-save' not in body


def test_change_username_success(member):
    resp = member.post("/account/username", data={"username": "GeaenderterName"},
                       follow_redirects=False)
    assert resp.status_code == 200
    assert storage.get_user_by_username("geaendertername") is not None


def test_change_username_rejects_duplicate(member):
    storage.create_user("occupied@test.de", "pw", username="Belegt")
    resp = member.post("/account/username", data={"username": "belegt"})
    assert resp.status_code == 409


def test_change_username_rejects_invalid(member):
    resp = member.post("/account/username", data={"username": "x@"})
    assert resp.status_code == 400


def test_adzuna_submit_persists_encrypted(member, monkeypatch):
    monkeypatch.setattr("jobscanner.search.validate_adzuna_keys", lambda a, b: True)
    resp = member.post("/einstellungen/adzuna",
                       data={"adzuna_app_id": "my-id", "adzuna_app_key": "my-key"},
                       follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/einstellungen?tab=anbindungen"
    uid = storage.get_user_by_email("m@test.de")["id"]
    aid_enc, akey_enc = storage.get_adzuna_keys_enc(uid)
    assert aid_enc and aid_enc != "my-id"        # verschlüsselt, kein Klartext
    assert akey_enc and akey_enc != "my-key"


def test_adzuna_submit_invalid_rejected(member, monkeypatch):
    monkeypatch.setattr("jobscanner.search.validate_adzuna_keys", lambda a, b: False)
    resp = member.post("/einstellungen/adzuna",
                       data={"adzuna_app_id": "x", "adzuna_app_key": "y"})
    assert "Adzuna" in resp.text and "abgelehnt" in resp.text
    uid = storage.get_user_by_email("m@test.de")["id"]
    assert storage.get_adzuna_keys_enc(uid) == (None, None)


def test_adzuna_delete_clears_keys(member, monkeypatch):
    monkeypatch.setattr("jobscanner.search.validate_adzuna_keys", lambda a, b: True)
    member.post("/einstellungen/adzuna",
                data={"adzuna_app_id": "i", "adzuna_app_key": "k"})
    resp = member.post("/einstellungen/adzuna/loeschen", data={}, follow_redirects=False)
    assert resp.status_code == 303
    uid = storage.get_user_by_email("m@test.de")["id"]
    assert storage.get_adzuna_keys_enc(uid) == (None, None)


def test_jooble_submit_and_delete(member, monkeypatch):
    monkeypatch.setattr("jobscanner.search.validate_jooble_key", lambda k: True)
    resp = member.post("/einstellungen/jooble", data={"jooble_key": "jk"},
                       follow_redirects=False)
    assert resp.status_code == 303
    uid = storage.get_user_by_email("m@test.de")["id"]
    assert storage.get_jooble_key_enc(uid) is not None
    member.post("/einstellungen/jooble/loeschen", data={})
    assert storage.get_jooble_key_enc(uid) is None


def test_jooble_invalid_rejected(member, monkeypatch):
    monkeypatch.setattr("jobscanner.search.validate_jooble_key", lambda k: False)
    resp = member.post("/einstellungen/jooble", data={"jooble_key": "bad"})
    assert "Jooble" in resp.text and "abgelehnt" in resp.text
