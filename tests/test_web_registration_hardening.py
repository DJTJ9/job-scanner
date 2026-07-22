import re

import pytest

from jobscanner import storage
from jobscanner.web.app import create_app
from _csrf_client import CSRFTestClient


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "ownerpw")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@test.de")
    monkeypatch.setenv("JOBSCANNER_INVITE_CODE", "invite123")
    monkeypatch.delenv("SMTP_HOST", raising=False)  # Mailer schlägt fehl -> Registrierung darf trotzdem klappen
    return create_app(db_path=tmp_path / "jobs.db")


def _register(client, email="m@test.de", consent="on"):
    data = {"email": email, "password": "pw123456", "invite_code": "invite123"}
    if consent is not None:
        data["consent"] = consent
    return client.post("/register", data=data, follow_redirects=False)


def test_register_without_consent_rejected_400(app):
    client = CSRFTestClient(app)
    resp = _register(client, consent=None)
    assert resp.status_code == 400
    assert storage.get_user_by_email("m@test.de") is None


def test_register_with_consent_creates_user_with_verify_token(app):
    client = CSRFTestClient(app)
    _register(client)
    user = storage.get_user_by_email("m@test.de")
    assert user is not None
    assert user["consent_at"] is not None
    assert user["verify_token"]
    assert user["email_verified_at"] is None


def test_register_stores_registering_ip(app):
    client = CSRFTestClient(app)
    _register(client)
    user = storage.get_user_by_email("m@test.de")
    assert user["registered_ip"] == "testclient"


def test_register_sixth_attempt_from_same_ip_rate_limited(app):
    client = CSRFTestClient(app)
    for i in range(5):
        _register(client, email=f"m{i}@test.de")
    resp = _register(client, email="m6@test.de")
    assert resp.status_code == 429
    assert storage.get_user_by_email("m6@test.de") is None


def test_login_sixth_attempt_from_same_ip_rate_limited(app):
    client = CSRFTestClient(app)
    for _ in range(5):
        client.post("/login", data={"email": "x@test.de", "password": "falsch"})
    resp = client.post("/login", data={"email": "x@test.de", "password": "falsch"})
    assert resp.status_code == 429


def test_unverified_member_redirected_from_dashboard_and_root(app):
    client = CSRFTestClient(app)
    _register(client)
    resp_root = client.get("/", follow_redirects=False)
    assert resp_root.status_code == 303
    assert resp_root.headers["location"] == "/verify-pending"


def test_verify_email_unlocks_dashboard_access(app):
    client = CSRFTestClient(app)
    _register(client)
    token = storage.get_user_by_email("m@test.de")["verify_token"]
    resp = client.get(f"/verify-email?token={token}", follow_redirects=False)
    assert resp.status_code == 303
    user = storage.get_user_by_email("m@test.de")
    assert user["email_verified_at"] is not None
    resp_root = client.get("/")
    assert resp_root.status_code == 200


def test_verify_email_rejects_unknown_token(app):
    client = CSRFTestClient(app)
    resp = client.get("/verify-email?token=nicht-existent")
    assert resp.status_code == 404


def test_owner_bypasses_hard_lock_without_verification(app):
    client = CSRFTestClient(app)
    client.post("/login", data={"email": "owner@test.de", "password": "ownerpw"})
    resp = client.get("/")
    assert resp.status_code == 200
