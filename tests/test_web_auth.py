"""Tests für Email/Passwort-Login, Logout und Session-Guard."""
import pytest
from fastapi.testclient import TestClient
from _csrf_client import CSRFTestClient

from jobscanner.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "geheim123")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@test.de")
    monkeypatch.setenv("JOBSCANNER_INVITE_CODE", "invite123")
    app = create_app(db_path=tmp_path / "jobs.db")
    return CSRFTestClient(app)


def test_root_shows_landing_when_unauthenticated(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 200
    assert 'href="/login"' in resp.text   # Landing mit Anmelden-CTA statt Redirect


def test_login_wrong_password_rejected(client):
    resp = client.post("/login", data={"email": "owner@test.de", "password": "falsch"})
    assert resp.status_code == 401
    assert "Falsche Zugangsdaten" in resp.text


def test_login_correct_sets_session_and_redirects(client):
    resp = client.post("/login", data={"email": "owner@test.de", "password": "geheim123"},
                       follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    resp2 = client.get("/", follow_redirects=False)
    assert resp2.status_code == 200


def test_owner_seeded_with_owner_role(client):
    from jobscanner import storage
    assert storage.get_user_by_email("owner@test.de")["role"] == "owner"


def test_logout_clears_session(client):
    client.post("/login", data={"email": "owner@test.de", "password": "geheim123"})
    client.get("/logout")
    resp = client.get("/jobs", follow_redirects=False)   # login-pflichtige Seite
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def _reg(client, **over):
    data = {"email": "neu@test.de", "username": "NeuUser", "password": "pw123456",
            "invite_code": "invite123", "consent": "on"}
    data.update(over)
    return client.post("/register", data=data, follow_redirects=False)


def test_register_requires_valid_username(client):
    # ungültig: zu kurz
    resp = _reg(client, username="ab")
    assert resp.status_code == 400
    # ungültig: enthält @
    resp = _reg(client, username="na@me")
    assert resp.status_code == 400


def test_register_username_uniqueness_409(client):
    from jobscanner import storage
    storage.create_user("first@test.de", "pw", username="Taken")
    resp = _reg(client, email="second@test.de", username="taken")
    assert resp.status_code == 409
    assert "Benutzername bereits vergeben" in resp.text


def test_register_sets_username_in_session(client):
    from jobscanner import storage
    resp = _reg(client, email="sess@test.de", username="SessName")
    assert resp.status_code == 303
    assert storage.get_user_by_username("sessname") is not None


def test_login_by_username_works(client):
    from jobscanner import storage
    storage.create_user("byname@test.de", "pw123456", username="LoginName")
    resp = client.post("/login", data={"email": "LoginName", "password": "pw123456"},
                       follow_redirects=False)
    assert resp.status_code == 303
    # GET / würde für einen frisch angelegten User ohne Profil zum Wizard
    # redirecten (leerer Body). /einstellungen braucht nur einen eingeloggten
    # User und rendert die Topbar mit der Login-Identität.
    home = client.get("/einstellungen", follow_redirects=False)
    assert "LoginName" in home.text   # Topbar zeigt username


def test_login_by_email_still_works(client):
    # Owner wird von der Fixture geseedet (owner@test.de / geheim123), hat keinen username
    resp = client.post("/login", data={"email": "owner@test.de", "password": "geheim123"},
                       follow_redirects=False)
    assert resp.status_code == 303
    home = client.get("/", follow_redirects=False)
    assert "owner@test.de" in home.text   # Fallback auf Email bei fehlendem username
