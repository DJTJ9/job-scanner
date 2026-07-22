"""Tests für Notify-Web: Dashboard-Banner + mark-on-visit + Toggle-Route."""
import pytest
from _csrf_client import CSRFTestClient

from jobscanner import storage
from jobscanner.models import Job
from jobscanner.web.app import create_app


@pytest.fixture
def member(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "geheim123")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@test.de")
    app = create_app(db_path=tmp_path / "jobs.db")
    uid = storage.create_user("m@test.de", "pw", role="member")
    storage.mark_email_verified(uid)
    c = CSRFTestClient(app)
    c.post("/login", data={"email": "m@test.de", "password": "pw"})
    return c, uid


def _pass_job(pid, title, score):
    fp = storage.upsert_job(Job(title=title, company="ACME", location="Hamburg",
                                first_seen="2026-07-20"))
    storage.upsert_job_score(pid, fp, score, "passt", "Pass", {})
    return fp


def test_dashboard_shows_banner_when_unnotified_pass_exists(member):
    c, uid = member
    pid = storage.create_profile("P", {}, user_id=uid)
    _pass_job(pid, "Senior Unity", 87)
    body = c.get(f"/dashboard/{pid}").text
    assert "notify-banner" in body
    assert "1 neue" in body


def test_dashboard_visit_marks_notified_and_clears_banner(member):
    c, uid = member
    pid = storage.create_profile("P", {}, user_id=uid)
    _pass_job(pid, "Senior Unity", 87)
    c.get(f"/dashboard/{pid}")
    assert storage.list_unnotified_top_matches(pid) == []
    body = c.get(f"/dashboard/{pid}").text
    assert "notify-banner" not in body


def test_dashboard_no_banner_without_pass(member):
    c, uid = member
    pid = storage.create_profile("P", {}, user_id=uid)
    body = c.get(f"/dashboard/{pid}").text
    assert "notify-banner" not in body
