"""Tests für /portale — Portal-Pre-Check-Tool Web-Routen."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from _csrf_client import CSRFTestClient

from jobscanner import storage
from jobscanner.web.app import create_app


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "ownerpw")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@test.de")
    return create_app(db_path=tmp_path / "jobs.db")


def _login(client, email="owner@test.de", pw="ownerpw"):
    return client.post("/login", data={"email": email, "password": pw})


def test_portale_requires_login(app):
    c = CSRFTestClient(app)
    resp = c.get("/portale", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_pruefen_compatible_shows_success_and_activate_button(app):
    c = CSRFTestClient(app)
    _login(c)
    with patch("jobscanner.web.app.precheck.precheck_portal",
              return_value={"rendered": True, "blocked": False, "structured": True,
                           "compatible": True}):
        resp = c.post("/portale/pruefen",
                      data={"url": "https://foo.de/karriere", "typ": "career_page"})
    assert resp.status_code == 200
    assert "Flachwasser" in resp.text
    assert "Zur Suchliste hinzufügen" in resp.text
    row = storage.list_custom_portals()[0]
    assert row["status"] == "compatible"


def test_pruefen_incompatible_shows_firecrawl_optin(app):
    c = CSRFTestClient(app)
    _login(c)
    with patch("jobscanner.web.app.precheck.precheck_portal",
              return_value={"rendered": True, "blocked": True, "structured": False,
                           "compatible": False}):
        resp = c.post("/portale/pruefen",
                      data={"url": "https://bar.de", "typ": "career_page"})
    assert resp.status_code == 200
    assert "Riff erkannt" in resp.text
    assert "Trotzdem mit Firecrawl aufnehmen" in resp.text


def test_aktivieren_sets_active_and_redirects(app):
    c = CSRFTestClient(app)
    _login(c)
    uid = storage.get_user_by_email("owner@test.de")["id"]
    pid = storage.create_custom_portal("https://foo.de", "career_page", uid)
    storage.save_check_result(pid, {"compatible": True})
    resp = c.post(f"/portale/aktivieren/{pid}", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/portale"
    assert storage.get_custom_portal(pid)["status"] == "active"


def test_portale_list_shows_all_users_entries(app):
    c = CSRFTestClient(app)
    _login(c)
    uid = storage.get_user_by_email("owner@test.de")["id"]
    storage.create_custom_portal("https://a.de", "career_page", uid)
    resp = c.get("/portale")
    assert "a.de" in resp.text


def _member(app, email="m@test.de", pw="memberpw"):
    """Member anlegen + eingeloggten CSRFTestClient zurückgeben."""
    storage.create_user(email, pw, role="member")
    c = CSRFTestClient(app)
    _login(c, email, pw)
    return c


def _owned_active_portal(owner_email):
    uid = storage.get_user_by_email(owner_email)["id"]
    pid = storage.create_custom_portal("https://foo.de", "career_page", uid)
    storage.save_check_result(pid, {"compatible": True})
    storage.activate_custom_portal(pid)
    return pid


def test_aktivieren_foreign_portal_forbidden(app):
    owner_c = CSRFTestClient(app); _login(owner_c)  # owner-Session nur zum Anlegen
    pid = _owned_active_portal("owner@test.de")
    storage.deactivate_custom_portal(pid)  # zurück auf inactive, damit aktivieren sinnvoll
    stranger = _member(app)
    resp = stranger.post(f"/portale/aktivieren/{pid}", follow_redirects=False)
    assert resp.status_code == 403
    assert storage.get_custom_portal(pid)["status"] == "inactive"


def test_aktivieren_missing_portal_redirects(app):
    c = CSRFTestClient(app); _login(c)
    resp = c.post("/portale/aktivieren/9999", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/portale"


def test_deaktivieren_by_owner_of_portal(app):
    stranger_uid = storage.create_user("owns@test.de", "pw", role="member")
    c = CSRFTestClient(app); _login(c, "owns@test.de", "pw")
    pid = storage.create_custom_portal("https://mine.de", "career_page", stranger_uid)
    storage.save_check_result(pid, {"compatible": True})
    storage.activate_custom_portal(pid)
    resp = c.post(f"/portale/deaktivieren/{pid}", follow_redirects=False)
    assert resp.status_code == 303
    assert storage.get_custom_portal(pid)["status"] == "inactive"


def test_deaktivieren_foreign_forbidden(app):
    owner_c = CSRFTestClient(app); _login(owner_c)
    pid = _owned_active_portal("owner@test.de")
    stranger = _member(app)
    resp = stranger.post(f"/portale/deaktivieren/{pid}", follow_redirects=False)
    assert resp.status_code == 403
    assert storage.get_custom_portal(pid)["status"] == "active"


def test_admin_owner_may_deaktivieren_any(app):
    stranger_uid = storage.create_user("s@test.de", "pw", role="member")
    pid = storage.create_custom_portal("https://s.de", "career_page", stranger_uid)
    storage.save_check_result(pid, {"compatible": True})
    admin = CSRFTestClient(app); _login(admin)  # owner
    storage.activate_custom_portal(pid)
    resp = admin.post(f"/portale/deaktivieren/{pid}", follow_redirects=False)
    assert resp.status_code == 303
    assert storage.get_custom_portal(pid)["status"] == "inactive"


def test_loeschen_by_owner_of_portal(app):
    uid = storage.create_user("d@test.de", "pw", role="member")
    c = CSRFTestClient(app); _login(c, "d@test.de", "pw")
    pid = storage.create_custom_portal("https://del.de", "career_page", uid)
    resp = c.post(f"/portale/loeschen/{pid}", follow_redirects=False)
    assert resp.status_code == 303
    assert storage.get_custom_portal(pid)["status"] == "deleted"
    assert all(p["id"] != pid for p in storage.list_custom_portals())


def test_loeschen_foreign_forbidden(app):
    owner_c = CSRFTestClient(app); _login(owner_c)
    pid = _owned_active_portal("owner@test.de")
    stranger = _member(app)
    resp = stranger.post(f"/portale/loeschen/{pid}", follow_redirects=False)
    assert resp.status_code == 403
    assert storage.get_custom_portal(pid)["status"] == "active"


def test_portale_list_shows_manage_buttons_for_owner(app):
    c = CSRFTestClient(app); _login(c)
    pid = _owned_active_portal("owner@test.de")
    resp = c.get("/portale")
    assert f"/portale/deaktivieren/{pid}" in resp.text
    assert f"/portale/loeschen/{pid}" in resp.text


def test_portale_list_hides_buttons_for_non_owner(app):
    owner_c = CSRFTestClient(app); _login(owner_c)
    pid = _owned_active_portal("owner@test.de")
    stranger = _member(app)
    resp = stranger.get("/portale")
    assert f"/portale/deaktivieren/{pid}" not in resp.text
    assert f"/portale/loeschen/{pid}" not in resp.text


def test_portale_list_shows_reaktivieren_for_inactive(app):
    c = CSRFTestClient(app); _login(c)
    pid = _owned_active_portal("owner@test.de")
    storage.deactivate_custom_portal(pid)
    resp = c.get("/portale")
    assert f"/portale/aktivieren/{pid}" in resp.text
    assert "Reaktivieren" in resp.text


def test_owner_creates_global_portal(app):
    c = CSRFTestClient(app); _login(c)  # owner
    with patch("jobscanner.web.app.precheck.precheck_portal",
              return_value={"compatible": True}):
        c.post("/portale/pruefen",
               data={"url": "https://studio.de/jobs", "typ": "career_page",
                     "is_global": "on"})
    assert any(p["is_global"] for p in storage.list_custom_portals())


def test_member_cannot_create_global_portal(app):
    member = _member(app)
    with patch("jobscanner.web.app.precheck.precheck_portal",
              return_value={"compatible": True}):
        member.post("/portale/pruefen",
                    data={"url": "https://studio.de/jobs", "typ": "career_page",
                          "is_global": "on"})
    assert not any(p["is_global"] for p in storage.list_custom_portals()
                   if p["url"] == "https://studio.de/jobs")


def test_global_group_labeled_on_portale_page(app):
    owner_uid = storage.get_user_by_email("owner@test.de")["id"]
    storage.create_custom_portal("https://empfohlen.de", "career_page",
                                 owner_uid, is_global=True)
    member = _member(app)
    resp = member.get("/portale")
    assert "Empfohlene Firmen" in resp.text
    assert "empfohlen.de" in resp.text
    # Nicht-Owner sieht keinen Lösch-Button auf dem globalen Eintrag:
    assert "/portale/loeschen/" not in resp.text


def test_scannable_portals_scoped_by_owner(app):
    from jobscanner import storage
    x = storage.create_user("x@test.de", "pw")
    y = storage.create_user("y@test.de", "pw")
    pid = storage.create_custom_portal(
        "https://evil.example", "portal", x,
        search_url_template="https://evil.example/s?q={query}",
        detail_url_pattern="https://evil.example/job/", is_global=False)
    storage.activate_custom_portal(pid)
    # Non-global Portal von X darf NICHT im Scan-Feed von Y erscheinen ...
    assert all(cp["id"] != pid for cp in storage.list_scannable_custom_portals(owner_id=y))
    # ... aber im eigenen Feed von X schon.
    assert any(cp["id"] == pid for cp in storage.list_scannable_custom_portals(owner_id=x))


def test_app_start_seeds_pool_as_global_active(app):
    from jobscanner import config
    pool_urls = {p["url"] for p in config.load_portale_pool()}
    rows = {p["url"]: p for p in storage.list_custom_portals()}
    assert pool_urls <= set(rows)
    for url in pool_urls:
        assert rows[url]["is_global"] is True
        assert rows[url]["status"] == "active"


def test_pool_meta_passed_to_template(app):
    from jobscanner import config
    eintrag = config.load_portale_pool()[0]
    c = CSRFTestClient(app); _login(c)
    resp = c.get("/portale")
    assert eintrag["label"] in resp.text
    assert eintrag["beschreibung"] in resp.text
