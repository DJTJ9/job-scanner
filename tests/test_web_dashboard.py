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


def test_feedback_records_vote(client):
    pid = storage.get_profile_by_name("Tjark")["id"]
    fp = storage.upsert_job(Job(title="Unity Dev", company="ACME", location="Hamburg",
                                first_seen="2026-07-11"))
    resp = client.post(f"/dashboard/{pid}/feedback/{fp}", data={"vote": "up"},
                       follow_redirects=False)
    assert resp.status_code == 303
    assert storage.get_feedback_map(pid)[fp] == "up"


def test_feedback_json_response_no_redirect(client):
    pid = storage.get_profile_by_name("Tjark")["id"]
    fp = storage.upsert_job(Job(title="Unity Dev", company="ACME", location="Hamburg",
                                first_seen="2026-07-11"))
    resp = client.post(f"/dashboard/{pid}/feedback/{fp}", data={"vote": "up"},
                       headers={"Accept": "application/json"}, follow_redirects=False)
    assert resp.status_code == 200
    assert resp.json() == {"vote": "up", "fingerprint": fp}
    assert storage.get_feedback_map(pid)[fp] == "up"


def test_feedback_json_response_invalid_vote_returns_null(client):
    pid = storage.get_profile_by_name("Tjark")["id"]
    fp = storage.upsert_job(Job(title="Unity Dev", company="ACME", location="Hamburg",
                                first_seen="2026-07-11"))
    resp = client.post(f"/dashboard/{pid}/feedback/{fp}", data={"vote": "invalid"},
                       headers={"Accept": "application/json"}, follow_redirects=False)
    assert resp.status_code == 200
    assert resp.json() == {"vote": None, "fingerprint": fp}


def test_dashboard_grid_and_sticky_rules_removed():
    css = Path("jobscanner/web/static/style.css").read_text()
    assert ".dashboard { display: grid" not in css
    assert "position: sticky; top: 1rem;" not in css
    assert "@media (max-width: 720px)" not in css


def test_panel_hidden_and_badge_styles_defined():
    css = Path("jobscanner/web/static/style.css").read_text()
    assert ".panel-hidden { display: none; }" in css
    assert ".feedback-badge-hidden { display: none; }" in css
    assert ".feedback-badge-up { color: var(--beute); }" in css
    assert ".feedback-badge-down { color: var(--veto); }" in css


def test_dashboard_has_toplevel_tabs_and_panels(client):
    pid = storage.get_profile_by_name("Tjark")["id"]
    resp = client.get(f"/dashboard/{pid}")
    assert 'data-tab-target="kontakte"' in resp.text
    assert 'data-tab-target="feintuning"' in resp.text
    assert 'data-tab-panel="kontakte"' in resp.text
    assert 'data-tab-panel="feintuning"' in resp.text
    assert 'class="panel feintuning panel-hidden"' in resp.text
    assert '<div class="dashboard">' not in resp.text


def test_dashboard_job_card_has_vote_hooks_and_hidden_badge(client):
    pid = storage.get_profile_by_name("Tjark")["id"]
    fp = storage.upsert_job(Job(title="Unrated Job", company="A", location="Hamburg",
                                first_seen="2026-07-11"))
    resp = client.get(f"/dashboard/{pid}")
    assert f'data-fingerprint="{fp}"' in resp.text
    assert "data-vote-form" in resp.text
    assert 'data-vote-btn="up"' in resp.text
    assert 'data-vote-btn="down"' in resp.text
    assert "feedback-badge-hidden" in resp.text


def test_dashboard_job_card_shows_badge_when_already_voted(client):
    pid = storage.get_profile_by_name("Tjark")["id"]
    fp = storage.upsert_job(Job(title="Rated Job", company="A", location="Hamburg",
                                first_seen="2026-07-11"))
    storage.add_feedback(pid, fp, "up")
    resp = client.get(f"/dashboard/{pid}")
    assert "feedback-badge-up" in resp.text
    assert "✓ bewertet 👍" in resp.text


def test_dashboard_requires_login(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "x")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "y")
    app = create_app(db_path=tmp_path / "jobs.db")
    anon = TestClient(app)
    resp = anon.get("/dashboard/1", follow_redirects=False)
    assert resp.status_code == 303
