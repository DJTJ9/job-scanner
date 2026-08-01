"""Tests für Notify-Web: Dashboard-Banner + mark-on-visit + Toggle-Route."""
import pytest
from _csrf_client import CSRFTestClient

from jobscanner import storage
from jobscanner.models import Job
from jobscanner.web.app import create_app


@pytest.fixture
def member(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "geheim123")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@test.de")
    app = create_app(db_path=tmp_path / "jobs.db")
    uid = storage.create_user("m@test.de", "pw", role="member")
    storage.mark_email_verified(uid)
    c = CSRFTestClient(app)
    c.post("/login", data={"email": "m@test.de", "password": "pw"})
    return c, uid


@pytest.fixture
def owner(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "ownerpw")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@test.de")
    app = create_app(db_path=tmp_path / "jobs.db")
    uid = storage.get_user_by_email("owner@test.de")["id"]
    c = CSRFTestClient(app)
    c.post("/login", data={"email": "owner@test.de", "password": "ownerpw"})
    return c, uid


def _stored_pref(uid):
    return storage.get_notify_pref(storage.list_profiles(user_id=uid)[0]["data"])


def _pass_job(pid, title, score):
    fp = storage.upsert_job(Job(title=title, company="ACME", location="Hamburg",
                                first_seen="2026-07-20"))
    storage.upsert_job_score(pid, fp, score, "passt", "Pass", {})
    return fp


def test_dashboard_shows_banner_when_unnotified_pass_exists(member):
    c, uid = member
    pid = storage.create_profile("P", {}, user_id=uid)
    _pass_job(pid, "Senior Unity", 87)
    body = c.get(f"/dashboard/{pid}").text
    assert "notify-banner" in body
    assert "1 neue" in body


def test_dashboard_visit_marks_notified_and_clears_banner(member):
    c, uid = member
    pid = storage.create_profile("P", {}, user_id=uid)
    _pass_job(pid, "Senior Unity", 87)
    c.get(f"/dashboard/{pid}")
    assert storage.list_unnotified_top_matches(pid) == []
    body = c.get(f"/dashboard/{pid}").text
    assert "notify-banner" not in body


def test_dashboard_no_banner_without_pass(member):
    c, uid = member
    pid = storage.create_profile("P", {}, user_id=uid)
    body = c.get(f"/dashboard/{pid}").text
    assert "notify-banner" not in body


def test_settings_shows_benachrichtigung_tab(member):
    c, uid = member
    body = c.get("/einstellungen").text
    assert 'data-tab="notify"' in body
    assert "Benachrichtigung" in body
    assert 'action="/einstellungen/notify"' in body


def test_settings_notify_tab_shows_email_mode_radios(member):
    c, uid = member
    storage.create_profile("P", {}, user_id=uid)
    body = c.get("/einstellungen").text
    assert 'name="email_mode"' in body
    assert 'value="daily"' in body and 'value="weekly"' in body and 'value="off"' in body
    assert 'name="immediate"' in body and 'name="inbox"' in body


def test_notify_post_persists_new_shape(owner):
    c, uid = owner
    storage.create_profile("P", {}, user_id=uid)
    resp = c.post("/einstellungen/notify",
                  data={"email_mode": "weekly", "inbox": "on"},  # immediate ungesetzt
                  follow_redirects=False)
    assert resp.status_code == 303
    prof = storage.list_profiles(user_id=uid)[0]
    assert storage.get_notify_pref(prof["data"]) == {
        "email_mode": "weekly", "immediate": False, "inbox": True}


def test_notify_post_defaults_invalid_email_mode_to_daily(owner):
    c, uid = owner
    storage.create_profile("P", {}, user_id=uid)
    c.post("/einstellungen/notify", data={"email_mode": "bogus"}, follow_redirects=False)
    prof = storage.list_profiles(user_id=uid)[0]
    assert storage.get_notify_pref(prof["data"])["email_mode"] == "daily"


def test_inbox_lists_unread_match_with_marker(member):
    c, uid = member
    pid = storage.create_profile("P", {}, user_id=uid)
    _pass_job(pid, "Senior Unity", 92)
    storage.sync_inbox_notifications(pid)
    body = c.get("/benachrichtigungen").text
    assert "Senior Unity" in body
    assert "●" in body  # ungelesen-Marker


def test_inbox_visit_marks_all_read(member):
    c, uid = member
    pid = storage.create_profile("P", {}, user_id=uid)
    _pass_job(pid, "Senior Unity", 92)
    storage.sync_inbox_notifications(pid)
    c.get("/benachrichtigungen")
    assert storage.count_unread(uid) == 0


def test_sidebar_badge_shows_unread_count(member):
    c, uid = member
    pid = storage.create_profile("P", {}, user_id=uid)
    _pass_job(pid, "Senior Unity", 92)
    storage.sync_inbox_notifications(pid)
    body = c.get("/jobs").text  # irgendeine Seite mit Sidebar
    assert "nav-badge" in body


def test_inbox_requires_login(member):
    c, uid = member
    c.get("/logout")
    resp = c.get("/benachrichtigungen", follow_redirects=False)
    assert resp.status_code in (302, 303)


def test_member_post_ohne_email_felder_behaelt_gespeicherte_prefs(member):
    c, uid = member
    storage.create_profile("P", {}, user_id=uid)
    storage.set_notify_pref(uid, {"email_mode": "weekly", "immediate": True, "inbox": True})
    c.post("/einstellungen/notify", data={"inbox": "on"})
    assert _stored_pref(uid) == {"email_mode": "weekly", "immediate": True, "inbox": True}


def test_member_post_schreibt_weiterhin_die_inbox_checkbox(member):
    c, uid = member
    storage.create_profile("P", {}, user_id=uid)
    storage.set_notify_pref(uid, {"email_mode": "weekly", "immediate": True, "inbox": True})
    c.post("/einstellungen/notify", data={})
    assert _stored_pref(uid) == {"email_mode": "weekly", "immediate": True, "inbox": False}


def test_owner_post_schreibt_alle_drei_felder(owner):
    c, uid = owner
    storage.create_profile("P", {}, user_id=uid)
    storage.set_notify_pref(uid, {"email_mode": "weekly", "immediate": True, "inbox": True})
    c.post("/einstellungen/notify", data={"email_mode": "off"})
    assert _stored_pref(uid) == {"email_mode": "off", "immediate": False, "inbox": False}


def test_settings_context_hat_is_owner_flag(member, owner):
    mc, _ = member
    oc, _ = owner
    assert "feld-inaktiv" in mc.get("/einstellungen?tab=notify").text
    assert "feld-inaktiv" not in oc.get("/einstellungen?tab=notify").text
