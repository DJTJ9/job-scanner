import pytest

from jobscanner import storage
from jobscanner.web.app import create_app
from _csrf_client import CSRFTestClient


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "ownerpw")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@test.de")
    return create_app(db_path=tmp_path / "jobs.db")


def _owner_client(app):
    c = CSRFTestClient(app)
    c.post("/login", data={"email": "owner@test.de", "password": "ownerpw"})
    return c


def test_admin_members_requires_login(app):
    c = CSRFTestClient(app)
    resp = c.get("/admin/members", follow_redirects=False)
    assert resp.status_code == 303


def test_admin_members_forbidden_for_member(app):
    storage.create_user("m@test.de", "pw123456", role="member")
    c = CSRFTestClient(app)
    c.post("/login", data={"email": "m@test.de", "password": "pw123456"})
    assert c.get("/admin/members").status_code == 403


def test_admin_members_lists_and_verifies(app):
    uid = storage.create_user("unver@test.de", "pw123456", role="member")
    assert storage.get_user(uid)["email_verified_at"] is None
    c = _owner_client(app)
    page = c.get("/admin/members")
    assert page.status_code == 200
    assert "unver@test.de" in page.text
    resp = c.post(f"/admin/members/{uid}/verify", follow_redirects=False)
    assert resp.status_code == 303
    assert storage.get_user(uid)["email_verified_at"] is not None


def test_admin_reset_password_sets_reset_token(app, monkeypatch):
    monkeypatch.setattr("jobscanner.web.mailer.send_password_reset_email",
                        lambda *a, **k: None)
    uid = storage.create_user("pwr@test.de", "pw123456", role="member")
    c = _owner_client(app)
    resp = c.post(f"/admin/members/{uid}/reset-password", follow_redirects=False)
    assert resp.status_code == 303
    assert storage.get_user(uid)["reset_token"] is not None
