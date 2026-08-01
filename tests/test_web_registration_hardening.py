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


def _register(client, email="m@test.de", consent="on", username="hardening"):
    data = {"email": email, "username": username, "password": "pw123456",
            "invite_code": "invite123"}
    if consent is not None:
        data["consent"] = consent
    return client.post("/register", data=data, follow_redirects=False)


def _register_unverified(client, email="unver@test.de", username="unverif"):
    """User im Vor-Feature-Zustand: unbestaetigt, mit verify_token.
    Muss ueber storage laufen — /register verifiziert jetzt sofort."""
    uid = storage.create_user(email, "pw123456", role="member", consent=True,
                              username=username)
    client.post("/login", data={"email": email, "password": "pw123456"})
    return uid


def test_register_without_consent_rejected_400(app):
    client = CSRFTestClient(app)
    resp = _register(client, consent=None)
    assert resp.status_code == 400
    assert storage.get_user_by_email("m@test.de") is None


def test_register_with_consent_creates_verified_user(app):
    client = CSRFTestClient(app)
    _register(client)
    user = storage.get_user_by_email("m@test.de")
    assert user is not None
    assert user["consent_at"] is not None
    assert user["email_verified_at"] is not None
    assert user["verify_token"] is None


def test_register_stores_registering_ip(app):
    client = CSRFTestClient(app)
    _register(client)
    user = storage.get_user_by_email("m@test.de")
    assert user["registered_ip"] == "testclient"


def test_register_sixth_attempt_from_same_ip_rate_limited(app):
    client = CSRFTestClient(app)
    for i in range(5):
        _register(client, email=f"m{i}@test.de", username=f"hardening{i}")
    resp = _register(client, email="m6@test.de", username="hardening6")
    assert resp.status_code == 429
    assert storage.get_user_by_email("m6@test.de") is None


def test_login_sixth_attempt_from_same_ip_rate_limited(app):
    client = CSRFTestClient(app)
    for _ in range(5):
        client.post("/login", data={"email": "x@test.de", "password": "falsch"})
    resp = client.post("/login", data={"email": "x@test.de", "password": "falsch"})
    assert resp.status_code == 429


def test_member_reaches_dashboard_directly_after_registration(app):
    client = CSRFTestClient(app)
    _register(client)
    resp_root = client.get("/", follow_redirects=False)
    assert resp_root.status_code == 200


def test_verify_email_unlocks_dashboard_access(app):
    client = CSRFTestClient(app)
    _register_unverified(client)
    token = storage.get_user_by_email("unver@test.de")["verify_token"]
    resp = client.get(f"/verify-email?token={token}", follow_redirects=False)
    assert resp.status_code == 303
    user = storage.get_user_by_email("unver@test.de")
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


def test_verify_email_resend_sends_mail_and_redirects_sent(app, monkeypatch):
    client = CSRFTestClient(app)
    _register_unverified(client)
    calls = []
    monkeypatch.setattr(
        "jobscanner.web.app.mailer.send_verification_email",
        lambda email, token, base_url: calls.append((email, token, base_url)))
    resp = client.post("/verify-email/resend", data={}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/verify-pending?sent=1"
    user = storage.get_user_by_email("unver@test.de")
    assert calls == [(user["email"], user["verify_token"], "https://job-scanner.thinkshark.de")]


def test_verify_email_resend_second_call_within_cooldown_redirects_cooldown(app, monkeypatch):
    client = CSRFTestClient(app)
    _register_unverified(client)
    monkeypatch.setattr(
        "jobscanner.web.app.mailer.send_verification_email", lambda *a: None)
    client.post("/verify-email/resend", data={})
    resp = client.post("/verify-email/resend", data={}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/verify-pending?cooldown=1"


def test_verify_email_resend_smtp_failure_redirects_error(app, monkeypatch):
    client = CSRFTestClient(app)
    _register_unverified(client)

    def _raise(*a):
        raise RuntimeError("smtp down")

    monkeypatch.setattr("jobscanner.web.app.mailer.send_verification_email", _raise)
    resp = client.post("/verify-email/resend", data={}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/verify-pending?error=1"


def test_verify_email_resend_requires_login(app):
    client = CSRFTestClient(app)
    resp = client.post("/verify-email/resend", data={}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_verify_email_resend_after_already_verified_redirects_home(app):
    client = CSRFTestClient(app)
    _register_unverified(client)
    token = storage.get_user_by_email("unver@test.de")["verify_token"]
    client.get(f"/verify-email?token={token}")
    resp = client.post("/verify-email/resend", data={}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


def test_verify_email_resend_generates_token_when_missing(app, monkeypatch):
    """Accounts von vor Einführung der Email-Verifizierung haben verify_token=NULL.
    Resend muss trotzdem funktionieren (Token frisch erzeugen), statt still ins Leere zu laufen."""
    client = CSRFTestClient(app)
    _register_unverified(client)
    user = storage.get_user_by_email("unver@test.de")
    # Token nachträglich löschen (simuliert Pre-Migration-Account)
    conn = storage._require_conn()
    conn.execute("UPDATE users SET verify_token = NULL WHERE id = ?", (user["id"],))
    conn.commit()
    calls = []
    monkeypatch.setattr(
        "jobscanner.web.app.mailer.send_verification_email",
        lambda email, token, base_url: calls.append((email, token, base_url)))
    resp = client.post("/verify-email/resend", data={}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/verify-pending?sent=1"
    fresh = storage.get_user_by_email("unver@test.de")
    assert fresh["verify_token"]  # neuer Token persistiert
    assert calls == [(fresh["email"], fresh["verify_token"], "https://job-scanner.thinkshark.de")]


def test_ensure_verify_token_keeps_existing(app):
    client = CSRFTestClient(app)
    _register_unverified(client)
    user = storage.get_user_by_email("unver@test.de")
    existing = user["verify_token"]
    assert existing
    assert storage.ensure_verify_token(user["id"]) == existing


def test_verify_pending_shows_resend_button(app):
    client = CSRFTestClient(app)
    _register(client)
    resp = client.get("/verify-pending")
    assert resp.status_code == 200
    assert 'action="/verify-email/resend"' in resp.text
    assert "Email erneut senden" in resp.text


def test_verify_pending_shows_sent_message(app):
    client = CSRFTestClient(app)
    _register(client)
    resp = client.get("/verify-pending?sent=1")
    assert "erneut gesendet" in resp.text


def test_verify_pending_shows_cooldown_message(app):
    client = CSRFTestClient(app)
    _register(client)
    resp = client.get("/verify-pending?cooldown=1")
    assert "kurz warten" in resp.text
    assert 'data-cooldown="60"' in resp.text


def test_verify_pending_shows_error_message(app):
    client = CSRFTestClient(app)
    _register(client)
    resp = client.get("/verify-pending?error=1")
    assert "Fehler beim Senden" in resp.text


def test_verify_pending_no_messages_without_query_params(app):
    client = CSRFTestClient(app)
    _register(client)
    resp = client.get("/verify-pending")
    assert "erneut gesendet" not in resp.text
    assert "60s warten" not in resp.text
    assert "Fehler beim Senden" not in resp.text
