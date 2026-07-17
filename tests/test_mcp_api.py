"""Tests für den BYO-Member-MCP-Zugang: Token, Tool-Scoping, Auth, Push-Validierung."""
import pytest
from fastapi.testclient import TestClient

from jobscanner import storage
from jobscanner.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "geheim123")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@test.de")
    app = create_app(db_path=tmp_path / "jobs.db")
    return TestClient(app)


@pytest.fixture
def member(client):
    uid = storage.create_user("member@test.de", "memberpw")
    token = storage.create_api_token(uid)
    return {"id": uid, "token": token}


class TestApiToken:
    def test_create_api_token_returns_bob_prefixed_plaintext(self, client):
        uid = storage.create_user("m1@test.de", "pw")
        token = storage.create_api_token(uid)
        assert token.startswith("bob_")
        assert len(token) == 4 + 48  # bob_ + 24 Hex-Bytes

    def test_token_stored_as_hash_not_plaintext(self, client):
        uid = storage.create_user("m2@test.de", "pw")
        token = storage.create_api_token(uid)
        user = storage.get_user(uid)
        assert user["api_token_hash"] != token
        assert token not in (user["api_token_hash"] or "")

    def test_get_user_by_api_token_roundtrip(self, client):
        uid = storage.create_user("m3@test.de", "pw")
        token = storage.create_api_token(uid)
        assert storage.get_user_by_api_token(token)["id"] == uid

    def test_get_user_by_api_token_invalid_returns_none(self, client):
        assert storage.get_user_by_api_token("bob_" + "0" * 48) is None
        assert storage.get_user_by_api_token("") is None

    def test_create_api_token_replaces_old_token(self, client):
        uid = storage.create_user("m4@test.de", "pw")
        old = storage.create_api_token(uid)
        new = storage.create_api_token(uid)
        assert storage.get_user_by_api_token(old) is None
        assert storage.get_user_by_api_token(new)["id"] == uid
