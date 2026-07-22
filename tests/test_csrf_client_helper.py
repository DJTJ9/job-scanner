import pytest

from jobscanner.web.app import create_app
from _csrf_client import CSRFTestClient


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "ownerpw")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@test.de")
    return create_app(db_path=tmp_path / "jobs.db")


def test_csrf_client_auto_injects_token_on_form_post(app):
    client = CSRFTestClient(app)
    resp = client.post("/login", data={"email": "owner@test.de", "password": "ownerpw"},
                       follow_redirects=False)
    assert resp.status_code == 303  # kein 403 CSRF-Fehler


def test_csrf_client_auto_injects_header_on_json_post(app):
    client = CSRFTestClient(app)
    client.post("/login", data={"email": "owner@test.de", "password": "ownerpw"})
    resp = client.post("/api/feedback", json={"text": "Test"})
    assert resp.status_code != 403
