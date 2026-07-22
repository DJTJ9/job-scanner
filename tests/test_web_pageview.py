"""Tests für Pageview-Logging-Middleware."""
import pytest
from fastapi.testclient import TestClient
from _csrf_client import CSRFTestClient

from jobscanner import storage
from jobscanner.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "geheim123")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@test.de")
    app = create_app(db_path=tmp_path / "jobs.db")
    c = CSRFTestClient(app)
    c.post("/login", data={"email": "owner@test.de", "password": "geheim123"})
    return c


def test_get_request_logs_pageview(client):
    before = storage.get_metrics_summary()["sessions_today"]
    client.get("/")
    after = storage.get_metrics_summary()["sessions_today"]
    assert after == before + 1


def test_static_asset_request_does_not_log_pageview(client):
    before = storage.get_metrics_summary()["sessions_today"]
    client.get("/static/style.css")
    after = storage.get_metrics_summary()["sessions_today"]
    assert after == before


def test_pageview_records_session_user_id(client):
    client.get("/")
    conn = storage._require_conn()
    row = conn.execute(
        "SELECT user_id FROM events WHERE event_type = 'pageview' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row["user_id"] is not None


def test_pageview_meta_records_request_path(client):
    client.get("/login")
    conn = storage._require_conn()
    row = conn.execute(
        "SELECT meta_json FROM events WHERE event_type = 'pageview' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert '"path": "/login"' in row["meta_json"]
