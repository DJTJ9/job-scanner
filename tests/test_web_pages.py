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


def test_scan_seite_zeigt_befehle_und_letzten_scan(client):
    resp = client.get("/scan")
    assert resp.status_code == 200
    assert "/bob:bob-scan" in resp.text
    assert "noch nie" in resp.text          # kein scan_pushed-Event in frischer DB


def test_profil_seite_listet_profile(client):
    resp = client.get("/profil")
    assert resp.status_code == 200
    assert "Tjark" in resp.text
    assert "/wizard/new" in resp.text


def test_metriken_owner_only(client):
    resp = client.get("/metriken")
    assert resp.status_code == 200
    assert "Aktive Member" in resp.text


def test_metriken_member_403(client, tmp_path):
    client.get("/logout")
    storage.create_user("m@test.de", "geheim123")
    storage.mark_email_verified(storage.get_user_by_email("m@test.de")["id"])
    client.post("/login", data={"email": "m@test.de", "password": "geheim123"})
    resp = client.get("/metriken")
    assert resp.status_code == 403


def test_sidebar_gruppen_und_aktiv_highlight(client):
    resp = client.get("/jobs")
    for href in ["/", "/jobs", "/favoriten", "/scan", "/feintuning", "/lernen",
                 "/portale", "/profil", "/einstellungen", "/account/email", "/hilfe",
                 "/metriken", "/admin/feedback"]:
        assert f'href="{href}"' in resp.text
    assert "drawer-group" in resp.text
    assert "drawer-item-active" in resp.text     # /jobs ist hervorgehoben
    assert 'href="/onboarding"' not in resp.text # Onboarding-Eintrag entfällt


def test_admin_gruppe_nur_owner(client):
    client.get("/logout")
    storage.create_user("m2@test.de", "geheim123")
    storage.mark_email_verified(storage.get_user_by_email("m2@test.de")["id"])
    client.post("/login", data={"email": "m2@test.de", "password": "geheim123"})
    resp = client.get("/hilfe")
    assert 'href="/metriken"' not in resp.text


def test_profil_switcher_nur_bei_mehreren_profilen(client):
    resp = client.get("/jobs")
    assert "data-profile-switcher" not in resp.text
    uid = storage.get_user_by_email("owner@test.de")["id"]
    storage.create_profile("Zweit", {"skills": []}, user_id=uid)
    resp = client.get("/jobs")
    assert "data-profile-switcher" in resp.text
