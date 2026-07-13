"""Tests für Profilwahl, Dashboard, Kriterien-Save, Feedback."""
import pytest
from fastapi.testclient import TestClient

from jobscanner import storage
from jobscanner.models import Job
from jobscanner.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "geheim123")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    app = create_app(db_path=tmp_path / "jobs.db")
    c = TestClient(app)
    c.post("/login", data={"password": "geheim123"})
    return c


def test_profiles_page_lists_active_profiles(client):
    resp = client.get("/")
    assert "Tjark" in resp.text  # migrate_yaml_profile() läuft beim App-Start


def test_dashboard_shows_criteria_and_empty_job_list(client):
    pid = storage.get_profile_by_name("Tjark")["id"]
    resp = client.get(f"/dashboard/{pid}")
    assert resp.status_code == 200
    assert "Passung zu Zielrollen" in resp.text  # DEFAULT_CRITERIA-Label


def test_dashboard_unknown_profile_redirects_home(client):
    resp = client.get("/dashboard/9999", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


def test_save_criteria_updates_weight(client):
    pid = storage.get_profile_by_name("Tjark")["id"]
    key = storage.list_criteria(pid)[0]["key"]
    resp = client.post(f"/dashboard/{pid}/criteria", data={f"weight_{key}": "1"},
                       follow_redirects=False)
    assert resp.status_code == 303
    assert storage.list_criteria(pid)[0]["weight"] == 1


def test_dashboard_shows_scored_job_with_breakdown(client):
    pid = storage.get_profile_by_name("Tjark")["id"]
    fp = storage.upsert_job(Job(title="Unity Dev", company="ACME", location="Hamburg",
                                first_seen="2026-07-11"))
    storage.upsert_job_score(pid, fp, 78, "passt gut", "Pass",
                             {"role_fit": {"punkte": 8, "grund": "starke Passung"}})
    resp = client.get(f"/dashboard/{pid}")
    assert "Unity Dev" in resp.text
    assert "78" in resp.text
    assert "starke Passung" in resp.text


def test_feedback_records_vote(client):
    pid = storage.get_profile_by_name("Tjark")["id"]
    fp = storage.upsert_job(Job(title="Unity Dev", company="ACME", location="Hamburg",
                                first_seen="2026-07-11"))
    resp = client.post(f"/dashboard/{pid}/feedback/{fp}", data={"vote": "up"},
                       follow_redirects=False)
    assert resp.status_code == 303
    assert storage.get_feedback_map(pid)[fp] == "up"


def test_dashboard_requires_login(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "x")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "y")
    app = create_app(db_path=tmp_path / "jobs.db")
    anon = TestClient(app)
    resp = anon.get("/dashboard/1", follow_redirects=False)
    assert resp.status_code == 303


def test_dashboard_aktiv_tab_excludes_no_go_and_downvoted(client):
    pid = storage.get_profile_by_name("Tjark")["id"]
    fp_pass = storage.upsert_job(Job(title="Pass Job", company="A", location="Hamburg",
                                     first_seen="2026-07-11"))
    fp_nogo = storage.upsert_job(Job(title="NoGo Job", company="B", location="Hamburg",
                                     first_seen="2026-07-11"))
    fp_down = storage.upsert_job(Job(title="Downvoted Job", company="C", location="Hamburg",
                                     first_seen="2026-07-11"))
    storage.upsert_job_score(pid, fp_pass, 90, "", "Pass", {})
    storage.upsert_job_score(pid, fp_nogo, 10, "", "No-Go", {})
    storage.upsert_job_score(pid, fp_down, 80, "", "Pass", {})
    storage.add_feedback(pid, fp_down, "down")
    resp = client.get(f"/dashboard/{pid}")
    assert "Pass Job" in resp.text
    assert "NoGo Job" not in resp.text
    assert "Downvoted Job" not in resp.text


def test_dashboard_no_go_tab_excludes_downvoted(client):
    pid = storage.get_profile_by_name("Tjark")["id"]
    fp_nogo = storage.upsert_job(Job(title="NoGo Job", company="B", location="Hamburg",
                                     first_seen="2026-07-11"))
    fp_down = storage.upsert_job(Job(title="Downvoted NoGo Job", company="C", location="Hamburg",
                                     first_seen="2026-07-11"))
    storage.upsert_job_score(pid, fp_nogo, 10, "", "No-Go", {})
    storage.upsert_job_score(pid, fp_down, 5, "", "No-Go", {})
    storage.add_feedback(pid, fp_down, "down")
    resp = client.get(f"/dashboard/{pid}", params={"tab": "no_go"})
    assert "NoGo Job" in resp.text
    assert "Downvoted NoGo Job" not in resp.text


def test_dashboard_bewertet_tab_shows_downvoted_regardless_of_category(client):
    pid = storage.get_profile_by_name("Tjark")["id"]
    fp_down = storage.upsert_job(Job(title="Downvoted Job", company="C", location="Hamburg",
                                     first_seen="2026-07-11"))
    storage.upsert_job_score(pid, fp_down, 80, "", "Pass", {})
    storage.add_feedback(pid, fp_down, "down")
    resp = client.get(f"/dashboard/{pid}", params={"tab": "bewertet"})
    assert "Downvoted Job" in resp.text


def test_dashboard_unscored_job_appears_in_aktiv_tab(client):
    pid = storage.get_profile_by_name("Tjark")["id"]
    storage.upsert_job(Job(title="Unscored Job", company="D", location="Hamburg",
                           first_seen="2026-07-11"))
    resp = client.get(f"/dashboard/{pid}")
    assert "Unscored Job" in resp.text


def test_dashboard_shows_tab_navigation_with_counts(client):
    pid = storage.get_profile_by_name("Tjark")["id"]
    fp_nogo = storage.upsert_job(Job(title="NoGo Job", company="B", location="Hamburg",
                                     first_seen="2026-07-11"))
    storage.upsert_job_score(pid, fp_nogo, 10, "", "No-Go", {})
    resp = client.get(f"/dashboard/{pid}")
    assert "Aktiv" in resp.text
    assert "No-Go" in resp.text
    resp_nogo = client.get(f"/dashboard/{pid}", params={"tab": "no_go"})
    assert "Bereits bewertet" in resp_nogo.text
