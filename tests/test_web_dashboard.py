"""Tests für Profilwahl, Dashboard, Kriterien-Save, Feedback."""
from pathlib import Path

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


def test_breakdown_table_has_fixed_layout_and_weighted_column_widths():
    css = Path("jobscanner/web/static/style.css").read_text()
    assert "table-layout: fixed;" in css
    assert ".breakdown-table th:nth-child(1), .breakdown-table td:nth-child(1) { width: 20%; }" in css
    assert ".breakdown-table th:nth-child(2), .breakdown-table td:nth-child(2) { width: 15%; }" in css
    assert ".breakdown-table th:nth-child(3), .breakdown-table td:nth-child(3) { width: 15%; }" in css
    assert ".breakdown-table th:nth-child(4), .breakdown-table td:nth-child(4) { width: 50%; }" in css


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
