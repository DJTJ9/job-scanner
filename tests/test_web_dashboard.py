"""Tests für Profilwahl, Dashboard, Kriterien-Save, Feedback."""
import subprocess
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


def test_dashboard_js_has_tab_switch_hooks():
    js = Path("jobscanner/web/static/dashboard.js").read_text()
    assert "data-tab-target" in js
    assert "data-tab-panel" in js
    assert "panel-hidden" in js


def test_dashboard_js_has_fetch_vote_hooks_with_inflight_disable():
    js = Path("jobscanner/web/static/dashboard.js").read_text()
    assert "data-vote-form" in js
    assert "preventDefault" in js
    assert "fetch(form.action" in js
    assert '"Accept"' in js and "application/json" in js
    assert "b.disabled = true" in js
    assert "data-feedback-badge" in js


def test_dashboard_requires_login(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "x")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "y")
    app = create_app(db_path=tmp_path / "jobs.db")
    anon = TestClient(app)
    resp = anon.get("/dashboard/1", follow_redirects=False)
    assert resp.status_code == 303


def test_read_asset_version_returns_git_short_hash():
    from jobscanner.web.app import _read_asset_version
    version = _read_asset_version(Path(__file__).parent.parent)
    assert len(version) == 7
    assert version != "unknown"


def test_read_asset_version_falls_back_when_not_a_git_repo(tmp_path):
    from jobscanner.web.app import _read_asset_version
    version = _read_asset_version(tmp_path)
    assert version == "unknown"


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


def _current_git_short_hash():
    return subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=Path(__file__).parent.parent,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def test_base_template_static_refs_use_git_hash_version(client):
    version = _current_git_short_hash()
    resp = client.get("/")
    assert f"/static/style.css?v={version}" in resp.text
    assert f"/static/app.js?v={version}" in resp.text


def test_dashboard_template_static_ref_uses_git_hash_version(client):
    version = _current_git_short_hash()
    pid = storage.get_profile_by_name("Tjark")["id"]
    resp = client.get(f"/dashboard/{pid}")
    assert f"/static/dashboard.js?v={version}" in resp.text
