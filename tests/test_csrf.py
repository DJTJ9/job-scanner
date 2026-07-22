import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from jobscanner import storage
from jobscanner.web import csrf
from jobscanner.web.app import create_app


def _request(session=None):
    scope = {"type": "http", "session": session if session is not None else {}}
    return Request(scope)


def test_ensure_token_creates_and_persists_token_in_session():
    req = _request()
    token = csrf.ensure_token(req)
    assert token
    assert req.session["csrf_token"] == token


def test_ensure_token_is_idempotent():
    req = _request()
    first = csrf.ensure_token(req)
    second = csrf.ensure_token(req)
    assert first == second


def test_verify_accepts_matching_token():
    req = _request()
    token = csrf.ensure_token(req)
    assert csrf.verify(req, token) is True


def test_verify_rejects_mismatch_missing_or_no_session_token():
    req = _request()
    csrf.ensure_token(req)
    assert csrf.verify(req, "falsch") is False
    assert csrf.verify(req, None) is False
    assert csrf.verify(req, "") is False
    empty_req = _request()
    assert csrf.verify(empty_req, "irgendwas") is False


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "ownerpw")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@test.de")
    monkeypatch.setenv("JOBSCANNER_INVITE_CODE", "invite123")
    return create_app(db_path=tmp_path / "jobs.db")


def test_login_post_without_csrf_token_rejected_403(app):
    client = TestClient(app)
    client.get("/login")  # seedet Session-Cookie + Token, aber wir senden ihn nicht mit
    resp = client.post("/login", data={"email": "owner@test.de", "password": "ownerpw"})
    assert resp.status_code == 403


def test_login_post_with_correct_csrf_token_succeeds(app):
    client = TestClient(app)
    html = client.get("/login").text
    import re
    token = re.search(r'name="csrf_token" value="([^"]*)"', html).group(1)
    resp = client.post("/login", data={"email": "owner@test.de", "password": "ownerpw",
                                       "csrf_token": token}, follow_redirects=False)
    assert resp.status_code == 303


def test_api_feedback_json_post_without_header_rejected_403(app):
    client = TestClient(app)
    client.get("/login")
    resp = client.post("/api/feedback", json={"text": "x"})
    assert resp.status_code == 403
