"""Tests für Funnel-Event-Logging an Wizard-Start/Profil-Erstellung/Feedback-Submit."""
import pytest
from fastapi.testclient import TestClient
from _csrf_client import CSRFTestClient

from jobscanner import storage
from jobscanner.models import Job
from jobscanner.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "geheim123")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@test.de")
    monkeypatch.setenv("JOBSCANNER_INVITE_CODE", "invite123")
    app = create_app(db_path=tmp_path / "jobs.db")
    c = CSRFTestClient(app)
    c.post("/register", data={"email": "member@test.de", "password": "pw123456",
                              "invite_code": "invite123", "consent": "on"})
    storage.mark_email_verified(storage.get_user_by_email("member@test.de")["id"])
    c.post("/login", data={"email": "member@test.de", "password": "pw123456"})
    return c


def test_wizard_start_logs_onboarding_start(client):
    client.get("/wizard/new")
    metrics = storage.get_metrics_summary()
    assert metrics["funnel_counts"]["onboarding_start"] == 1


def test_wizard_completion_logs_profil_erstellt_on_create_only(client):
    client.get("/wizard/new")
    client.post("/wizard/basis", data={"name": "P1"})
    resp = client.post("/wizard/gewichte", data={}, follow_redirects=False)
    assert resp.status_code == 303
    pid = int(resp.headers["location"].rsplit("/", 1)[1])
    assert storage.get_metrics_summary()["funnel_counts"]["profil_erstellt"] == 1

    client.get(f"/wizard/edit/{pid}")
    client.post("/wizard/gewichte", data={}, follow_redirects=False)
    assert storage.get_metrics_summary()["funnel_counts"]["profil_erstellt"] == 1


def test_feedback_valid_vote_logs_feedback_gegeben(client):
    uid = storage.get_user_by_email("member@test.de")["id"]
    pid = storage.create_profile("P2", {}, user_id=uid)
    fp = storage.upsert_job(Job(title="X", company="Y", location="Z"))
    resp = client.post(f"/dashboard/{pid}/feedback/{fp}", data={"vote": "up"},
                       follow_redirects=False)
    assert resp.status_code == 303
    assert storage.get_metrics_summary()["funnel_counts"]["feedback_gegeben"] == 1


def test_feedback_invalid_vote_does_not_log(client):
    uid = storage.get_user_by_email("member@test.de")["id"]
    pid = storage.create_profile("P3", {}, user_id=uid)
    fp = storage.upsert_job(Job(title="X2", company="Y2", location="Z2"))
    client.post(f"/dashboard/{pid}/feedback/{fp}", data={"vote": "bogus"})
    assert storage.get_metrics_summary()["funnel_counts"]["feedback_gegeben"] == 0
