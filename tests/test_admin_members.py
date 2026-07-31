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
