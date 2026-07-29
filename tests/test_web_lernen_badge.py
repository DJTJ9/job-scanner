"""Lernen-Badge: LLM-Feintuning gesperrt vor erstem Insight, frei danach (Member-Sicht)."""
import pytest
from _csrf_client import CSRFTestClient

from jobscanner import storage
from jobscanner.web.app import create_app


@pytest.fixture
def member(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "geheim123")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@test.de")
    app = create_app(db_path=tmp_path / "jobs.db")
    uid = storage.create_user("member@test.de", "pw", role="member")
    storage.mark_email_verified(uid)
    pid = storage.create_profile("MemberProfil", {}, user_id=uid)
    c = CSRFTestClient(app)
    c.post("/login", data={"email": "member@test.de", "password": "pw"})
    return c, pid


def test_badge_gesperrt_ohne_insight(member):
    client, _pid = member
    resp = client.get("/lernen")
    assert resp.status_code == 200
    assert "freigeschaltet" in resp.text  # Sperr-Hinweis-Text
    assert "LLM-Feintuning aktiv" not in resp.text


def test_badge_frei_nach_insight(member):
    client, pid = member
    storage.confirm_insight(storage.add_insight(pid, "preference", "x", source="member"), pid)
    resp = client.get("/lernen")
    assert "LLM-Feintuning aktiv" in resp.text
