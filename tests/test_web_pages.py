"""Tests für die neuen flachen Seiten (/jobs, /favoriten, /feintuning, /lernen, /scan, /profil, /metriken)."""
import pytest
from _csrf_client import CSRFTestClient

from jobscanner import storage
from jobscanner.models import Job
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


def _pid():
    return storage.get_profile_by_name("Tjark")["id"]


def test_jobs_zeigt_gescorten_job(client):
    fp = storage.upsert_job(Job(title="Unity Dev", company="ACME", location="Hamburg",
                                first_seen="2026-07-27"))
    storage.upsert_job_score(_pid(), fp, 78, "passt gut", "Pass", {})
    resp = client.get("/jobs")
    assert resp.status_code == 200
    assert "Unity Dev" in resp.text
    assert "78" in resp.text


def test_jobs_tabs_und_suche(client):
    fp = storage.upsert_job(Job(title="Godot Dev", company="ACME", location="Hamburg",
                                first_seen="2026-07-27"))
    storage.upsert_job_score(_pid(), fp, 60, "ok", "Pass", {})
    resp = client.get("/jobs?tab=aktiv&q=godot")
    assert "Godot Dev" in resp.text
    resp = client.get("/jobs?tab=aktiv&q=xyzzy")
    assert "Godot Dev" not in resp.text


def test_jobs_ohne_login_redirect(client):
    client.get("/logout")
    resp = client.get("/jobs", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_feedback_redirect_ziel_jobs(client):
    fp = storage.upsert_job(Job(title="X", company="Y", location="Z",
                                first_seen="2026-07-27"))
    resp = client.post(f"/dashboard/{_pid()}/feedback/{fp}", data={"vote": "up"},
                       follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/jobs"


def test_favoriten_zeigt_favorisierte_jobs(client):
    pid = _pid()
    fp = storage.upsert_job(Job(title="Fav Dev", company="ACME", location="HH",
                                first_seen="2026-07-27"))
    storage.upsert_job_score(pid, fp, 80, "gut", "Pass", {})
    storage.toggle_favorite(pid, fp)
    resp = client.get("/favoriten")
    assert resp.status_code == 200
    assert "Fav Dev" in resp.text


def test_feintuning_zeigt_kriterien(client):
    resp = client.get("/feintuning")
    assert resp.status_code == 200
    assert "Passung zu Zielrollen" in resp.text     # DEFAULT_CRITERIA-Label


def test_criteria_post_redirect_feintuning(client):
    pid = _pid()
    key = storage.list_criteria(pid)[0]["key"]
    resp = client.post(f"/dashboard/{pid}/criteria", data={f"weight_{key}": "2"},
                       follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/feintuning"


def test_lernen_rendert_mit_analysis_base(client):
    resp = client.get("/lernen")
    assert resp.status_code == 200
    assert f'data-analysis-base="/dashboard/{_pid()}"' in resp.text
