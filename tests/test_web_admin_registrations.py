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


def test_admin_registrations_requires_login(app):
    client = CSRFTestClient(app)
    resp = client.get("/admin/registrations", follow_redirects=False)
    assert resp.status_code == 303


def test_admin_registrations_forbidden_for_member(app):
    storage.create_user("member@test.de", "pw123456", role="member")
    client = CSRFTestClient(app)
    client.post("/login", data={"email": "member@test.de", "password": "pw123456"})
    resp = client.get("/admin/registrations")
    assert resp.status_code == 403


def test_admin_registrations_lists_members_with_status_and_rate_limit(app):
    uid = storage.create_user("spam@bot.io", "pw123456", consent=True, ip="9.9.9.9")
    verified_id = storage.create_user("max@example.com", "pw123456", consent=True, ip="1.1.1.1")
    storage.mark_email_verified(verified_id)
    client = CSRFTestClient(app)
    for _ in range(3):
        app.state.rate_limiter.hit("register:9.9.9.9")
    client.post("/login", data={"email": "owner@test.de", "password": "ownerpw"})
    resp = client.get("/admin/registrations")
    assert resp.status_code == 200
    assert "spam@bot.io" in resp.text
    assert "max@example.com" in resp.text
    assert resp.text.index("spam@bot.io") < resp.text.index("max@example.com")  # älteste zuerst
