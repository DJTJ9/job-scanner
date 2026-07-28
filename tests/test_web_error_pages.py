"""Globale HTML-Fehlerseiten (404/500) — API-Pfade und Accept: json bleiben JSON."""
import pytest
from fastapi.testclient import TestClient

from jobscanner import storage
from jobscanner.web.app import create_app
from _csrf_client import CSRFTestClient


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "geheim123")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@test.de")
    return create_app(db_path=tmp_path / "jobs.db")


def test_404_page_renders_html(app):
    resp = TestClient(app).get("/gibt-es-nicht")
    assert resp.status_code == 404
    assert "text/html" in resp.headers["content-type"]
    assert "Seite nicht gefunden" in resp.text


def test_404_api_path_stays_json(app):
    resp = TestClient(app).get("/api/gibt-es-nicht")
    assert resp.status_code == 404
    assert "application/json" in resp.headers["content-type"]


def test_404_accept_json_stays_json(app):
    resp = TestClient(app).get("/gibt-es-nicht", headers={"accept": "application/json"})
    assert resp.status_code == 404
    assert "application/json" in resp.headers["content-type"]


def test_500_page_renders_html_no_stacktrace(app, monkeypatch):
    login = CSRFTestClient(app)
    resp = login.post("/login", data={"email": "owner@test.de", "password": "geheim123"})
    assert resp.status_code in (200, 303)

    def boom(*args, **kwargs):
        raise RuntimeError("kaboom-secret")

    monkeypatch.setattr(storage, "get_home_summary", boom)

    client = TestClient(app, raise_server_exceptions=False)
    client.cookies.update(login.cookies)
    resp = client.get("/", headers={"accept": "text/html"})
    assert resp.status_code == 500
    assert "text/html" in resp.headers["content-type"]
    assert "schiefgelaufen" in resp.text
    assert "kaboom-secret" not in resp.text
