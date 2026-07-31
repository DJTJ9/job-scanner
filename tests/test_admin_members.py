import pytest
from fastapi.testclient import TestClient

from jobscanner import config, storage
from jobscanner.web.app import create_app
from _csrf_client import CSRFTestClient


@pytest.fixture
def app(tmp_path, monkeypatch):
    # config._load_env() schreibt die echte .env per os.environ.setdefault prozessglobal
    # (monkeypatch nimmt das nicht zurück) — ins Leere zeigen lassen, sonst leakt diese
    # Datei SMTP-/Base-URL-Werte in nachfolgende Tests.
    monkeypatch.setattr(config, "_ENV_FILE", tmp_path / "none.env")
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "ownerpw")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@test.de")
    return create_app(db_path=tmp_path / "jobs.db")


def _owner_client(app):
    c = CSRFTestClient(app)
    c.post("/login", data={"email": "owner@test.de", "password": "ownerpw"})
    return c


def test_blocked_at_column_exists_and_defaults_null(app):
    uid = storage.create_user("neu@test.de", "pw123456", role="member")
    assert storage.get_user(uid)["blocked_at"] is None


def test_block_prevents_web_login(app):
    uid = storage.create_user("gesperrt@test.de", "pw123456", role="member")
    assert storage.verify_login("gesperrt@test.de", "pw123456") is not None
    storage.admin_block_user(uid)
    assert storage.get_user(uid)["blocked_at"] is not None
    assert storage.verify_login("gesperrt@test.de", "pw123456") is None


def test_block_prevents_username_login(app):
    uid = storage.create_user("uname@test.de", "pw123456", role="member")
    storage.set_username(uid, "bobby")
    assert storage.verify_login("bobby", "pw123456") is not None
    storage.admin_block_user(uid)
    assert storage.verify_login("bobby", "pw123456") is None


def test_unblock_restores_login(app):
    uid = storage.create_user("wieder@test.de", "pw123456", role="member")
    storage.admin_block_user(uid)
    storage.admin_unblock_user(uid)
    assert storage.get_user(uid)["blocked_at"] is None
    assert storage.verify_login("wieder@test.de", "pw123456") is not None


def test_block_prevents_api_token_lookup(app):
    uid = storage.create_user("token@test.de", "pw123456", role="member")
    token = storage.create_api_token(uid)
    assert storage.get_user_by_api_token(token) is not None
    storage.admin_block_user(uid)
    assert storage.get_user_by_api_token(token) is None
    storage.admin_unblock_user(uid)
    assert storage.get_user_by_api_token(token) is not None


def test_admin_list_members_exposes_blocked_at(app):
    uid = storage.create_user("liste@test.de", "pw123456", role="member")
    storage.admin_block_user(uid)
    row = next(m for m in storage.admin_list_members() if m["id"] == uid)
    assert row["blocked_at"] is not None


def test_sperren_requires_owner(app):
    uid = storage.create_user("opfer@test.de", "pw123456", role="member")
    storage.create_user("m@test.de", "pw123456", role="member")
    c = CSRFTestClient(app)
    c.post("/login", data={"email": "m@test.de", "password": "pw123456"})
    assert c.post(f"/admin/members/{uid}/sperren", follow_redirects=False).status_code == 403
    assert storage.get_user(uid)["blocked_at"] is None


def test_sperren_without_csrf_token_is_rejected(app):
    uid = storage.create_user("csrf@test.de", "pw123456", role="member")
    c = _owner_client(app)
    resp = TestClient.post(c, f"/admin/members/{uid}/sperren", data={"csrf_token": "falsch"},
                           follow_redirects=False)
    assert resp.status_code == 403
    assert storage.get_user(uid)["blocked_at"] is None


def test_sperren_and_entsperren_roundtrip(app):
    uid = storage.create_user("rt@test.de", "pw123456", role="member")
    c = _owner_client(app)
    resp = c.post(f"/admin/members/{uid}/sperren", follow_redirects=False)
    assert resp.status_code == 303
    assert storage.get_user(uid)["blocked_at"] is not None
    resp = c.post(f"/admin/members/{uid}/entsperren", follow_redirects=False)
    assert resp.status_code == 303
    assert storage.get_user(uid)["blocked_at"] is None


def test_sperren_own_account_forbidden(app):
    c = _owner_client(app)
    owner = storage.get_user_by_email("owner@test.de")
    resp = c.post(f"/admin/members/{owner['id']}/sperren", follow_redirects=False)
    assert resp.status_code == 403
    assert storage.get_user(owner["id"])["blocked_at"] is None


def test_sperren_other_owner_forbidden(app):
    other = storage.create_user("owner2@test.de", "pw123456", role="owner")
    c = _owner_client(app)
    assert c.post(f"/admin/members/{other}/sperren",
                  follow_redirects=False).status_code == 403
    assert storage.get_user(other)["blocked_at"] is None


def test_loeschen_get_shows_confirmation_page(app):
    uid = storage.create_user("weg@test.de", "pw123456", role="member")
    c = _owner_client(app)
    page = c.get(f"/admin/members/{uid}/loeschen")
    assert page.status_code == 200
    assert "weg@test.de" in page.text
    assert "confirm_email" in page.text
    assert storage.get_user(uid) is not None


def test_loeschen_with_wrong_email_does_not_delete(app):
    uid = storage.create_user("bleibt@test.de", "pw123456", role="member")
    c = _owner_client(app)
    resp = c.post(f"/admin/members/{uid}/loeschen",
                  data={"confirm_email": "falsch@test.de"}, follow_redirects=False)
    assert resp.status_code == 400
    assert "stimmt nicht überein" in resp.text
    assert storage.get_user(uid) is not None


def test_loeschen_with_matching_email_deletes(app):
    uid = storage.create_user("tschuess@test.de", "pw123456", role="member")
    c = _owner_client(app)
    resp = c.post(f"/admin/members/{uid}/loeschen",
                  data={"confirm_email": "  tschuess@test.de  "}, follow_redirects=False)
    assert resp.status_code == 303
    assert storage.get_user(uid) is None


def test_loeschen_own_and_owner_account_forbidden(app):
    owner = storage.get_user_by_email("owner@test.de")
    other = storage.create_user("owner3@test.de", "pw123456", role="owner")
    c = _owner_client(app)
    assert c.get(f"/admin/members/{owner['id']}/loeschen").status_code == 403
    assert c.get(f"/admin/members/{other}/loeschen").status_code == 403
    assert storage.get_user(other) is not None


def test_loeschen_logs_audit_event_under_admin_id(app):
    uid = storage.create_user("audit@test.de", "pw123456", role="member")
    owner = storage.get_user_by_email("owner@test.de")
    c = _owner_client(app)
    c.post(f"/admin/members/{uid}/loeschen", data={"confirm_email": "audit@test.de"},
           follow_redirects=False)
    rows = storage._require_conn().execute(
        "SELECT event_type, user_id, meta_json FROM events "
        "WHERE event_type = 'admin_member_geloescht'").fetchall()
    assert len(rows) == 1
    assert rows[0]["user_id"] == owner["id"]
    assert "audit@test.de" in rows[0]["meta_json"]


def test_members_page_shows_status_and_action_buttons(app):
    uid = storage.create_user("zeile@test.de", "pw123456", role="member")
    c = _owner_client(app)
    page = c.get("/admin/members")
    assert f"/admin/members/{uid}/sperren" in page.text
    assert f"/admin/members/{uid}/loeschen" in page.text
    assert "aktiv" in page.text


def test_members_page_shows_entsperren_for_blocked_member(app):
    uid = storage.create_user("gesperrt2@test.de", "pw123456", role="member")
    storage.admin_block_user(uid)
    c = _owner_client(app)
    page = c.get("/admin/members")
    assert f"/admin/members/{uid}/entsperren" in page.text
    assert f"/admin/members/{uid}/sperren\"" not in page.text
    assert "gesperrt" in page.text


def test_members_page_hides_danger_actions_for_own_and_owner_rows(app):
    owner = storage.get_user_by_email("owner@test.de")
    other = storage.create_user("owner4@test.de", "pw123456", role="owner")
    c = _owner_client(app)
    page = c.get("/admin/members")
    assert f"/admin/members/{owner['id']}/sperren" not in page.text
    assert f"/admin/members/{owner['id']}/loeschen" not in page.text
    assert f"/admin/members/{other}/sperren" not in page.text
    assert f"/admin/members/{other}/loeschen" not in page.text
