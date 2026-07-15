"""Tests für Registrierung, Login-Isolation und LLM-Rollen-Gate der Kommilitoninnen-Accounts."""
import pytest
from fastapi.testclient import TestClient

from jobscanner import storage
from jobscanner.web.app import create_app


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "ownerpw")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@test.de")
    monkeypatch.setenv("JOBSCANNER_INVITE_CODE", "komm2026")
    return create_app(db_path=tmp_path / "jobs.db")


def _register(client, email="stud@uni.de", pw="studpw", code="komm2026"):
    return client.post("/register",
                       data={"email": email, "password": pw, "invite_code": code},
                       follow_redirects=False)


def _wizard_profile(client, name):
    client.get("/wizard/new")
    client.post("/wizard/basis", data={"name": name, "level": "junior", "experience_years": "1"})
    client.post("/wizard/skills", data={"skills": "Python"})
    client.post("/wizard/zielrollen", data={"target_roles": "Backend"})
    client.post("/wizard/ort_umfang", data={"location": "Remote", "employment": "Vollzeit",
                                            "languages": "de"})
    client.post("/wizard/no_gos", data={"no_gos": ""})
    resp = client.post("/wizard/gewichte", data={}, follow_redirects=False)
    return resp.headers["location"]  # /dashboard/<id>


def test_register_valid_invite_creates_member_and_logs_in(app):
    c = TestClient(app)
    resp = _register(c)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    user = storage.get_user_by_email("stud@uni.de")
    assert user["role"] == "member"
    assert c.get("/", follow_redirects=False).status_code == 200


def test_register_wrong_invite_rejected(app):
    c = TestClient(app)
    resp = _register(c, code="falsch")
    assert resp.status_code == 403
    assert storage.get_user_by_email("stud@uni.de") is None


def test_register_duplicate_email_rejected(app):
    c = TestClient(app)
    _register(c)
    resp = TestClient(app).post(
        "/register", data={"email": "stud@uni.de", "password": "x", "invite_code": "komm2026"})
    assert resp.status_code == 409
