"""Tests für Profilwahl, Dashboard, Kriterien-Save, Feedback."""
import subprocess
from pathlib import Path
from unittest.mock import patch

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
    app = create_app(db_path=tmp_path / "jobs.db")
    c = CSRFTestClient(app)
    c.post("/login", data={"email": "owner@test.de", "password": "geheim123"})
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


def test_dashboard_job_title_links_to_source_when_sources_present(client):
    pid = storage.get_profile_by_name("Tjark")["id"]
    fp = storage.upsert_job(Job(title="Unity Dev", company="ACME", location="Hamburg",
                                first_seen="2026-07-11",
                                sources=[{"portal": "stepstone", "url": "https://example.com/job/123",
                                          "found_at": "2026-07-11"}]))
    resp = client.get(f"/dashboard/{pid}")
    assert '<a class="link" href="https://example.com/job/123" target="_blank" rel="noopener">Unity Dev</a>' in resp.text


def test_dashboard_job_title_plain_text_when_no_sources(client):
    pid = storage.get_profile_by_name("Tjark")["id"]
    storage.upsert_job(Job(title="Unity Dev", company="ACME", location="Hamburg",
                           first_seen="2026-07-11"))
    resp = client.get(f"/dashboard/{pid}")
    assert "<strong>Unity Dev</strong>" in resp.text
    assert '<a class="link"' not in resp.text.split("<strong>Unity Dev</strong>")[0][-200:]


def test_dashboard_job_title_plain_text_when_source_url_has_unsafe_scheme(client):
    pid = storage.get_profile_by_name("Tjark")["id"]
    storage.upsert_job(Job(title="Unity Dev", company="ACME", location="Hamburg",
                           first_seen="2026-07-11",
                           sources=[{"portal": "stepstone", "url": "javascript:alert(1)",
                                     "found_at": "2026-07-11"}]))
    resp = client.get(f"/dashboard/{pid}")
    assert "<strong>Unity Dev</strong>" in resp.text
    assert "javascript:" not in resp.text


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
    anon = CSRFTestClient(app)
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


def test_dashboard_ausland_tab_excludes_foreign_jobs_from_aktiv(client):
    pid = storage.get_profile_by_name("Tjark")["id"]
    storage.upsert_job(Job(title="DE Job", company="A", location="Hamburg",
                           first_seen="2026-07-11"))
    storage.upsert_job(Job(title="Ausland Job", company="B", location="New York",
                           first_seen="2026-07-11"))
    resp = client.get(f"/dashboard/{pid}")
    assert "DE Job" in resp.text
    assert "Ausland Job" not in resp.text


def test_dashboard_ausland_tab_shows_foreign_jobs(client):
    pid = storage.get_profile_by_name("Tjark")["id"]
    storage.upsert_job(Job(title="DE Job", company="A", location="Hamburg",
                           first_seen="2026-07-11"))
    storage.upsert_job(Job(title="Ausland Job", company="B", location="New York",
                           first_seen="2026-07-11"))
    resp = client.get(f"/dashboard/{pid}", params={"tab": "ausland"})
    assert "Ausland Job" in resp.text
    assert "DE Job" not in resp.text


def test_dashboard_shows_ausland_tab_with_count(client):
    pid = storage.get_profile_by_name("Tjark")["id"]
    storage.upsert_job(Job(title="Ausland Job", company="B", location="New York",
                           first_seen="2026-07-11"))
    resp = client.get(f"/dashboard/{pid}")
    assert "Ausland" in resp.text
    assert "(1)" in resp.text


def test_dashboard_shows_tab_navigation_with_counts(client):
    pid = storage.get_profile_by_name("Tjark")["id"]
    fp_nogo = storage.upsert_job(Job(title="NoGo Job", company="B", location="Hamburg",
                                     first_seen="2026-07-11"))
    storage.upsert_job_score(pid, fp_nogo, 10, "", "No-Go", {})
    resp = client.get(f"/dashboard/{pid}")
    assert "Aktiv" in resp.text
    assert "Aussortiert" in resp.text
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


def test_job_card_flex_child_has_min_width_zero():
    css = Path("jobscanner/web/static/style.css").read_text()
    assert ".job-card > div { min-width: 0; }" in css


def test_breakdown_table_and_job_meta_have_overflow_wrap():
    css = Path("jobscanner/web/static/style.css").read_text()
    assert ".breakdown-table td { overflow-wrap: anywhere; }" in css
    assert ".job-meta { color: #9fb3ba; font-size: 0.85rem; overflow-wrap: anywhere; }" in css


def test_save_criteria_triggers_rescore(client, monkeypatch):
    from unittest.mock import MagicMock
    pid = storage.get_profile_by_name("Tjark")["id"]
    mock = MagicMock(return_value=[])
    monkeypatch.setattr(storage, "rescore_profile", mock)
    key = storage.list_criteria(pid)[0]["key"]
    client.post(f"/dashboard/{pid}/criteria", data={f"weight_{key}": "1"},
                follow_redirects=False)
    mock.assert_called_once_with(pid)


def test_save_criteria_recomputes_scores_from_breakdown(client):
    pid = storage.get_profile_by_name("Tjark")["id"]
    fp = storage.upsert_job(Job(title="Unity Dev", company="ACME", location="Hamburg",
                                first_seen="2026-07-11"))
    storage.upsert_job_score(pid, fp, 0, "alt", "No-Go",
                             {"role_fit": {"punkte": 8, "grund": "passt"}})
    data = {f"weight_{c['key']}": ("5" if c["key"] == "role_fit" else "0")
            for c in storage.list_criteria(pid)}
    with patch("jobscanner.web.app.nocodb_board.push_job", return_value=1):
        resp = client.post(f"/dashboard/{pid}/criteria", data=data, follow_redirects=False)
    assert resp.status_code == 303
    assert storage.get_job_score(pid, fp)["score"] == 80


def test_breakdown_table_wrapped_in_scroll_container_with_min_width():
    html = Path("jobscanner/web/templates/dashboard.html").read_text()
    assert '<div class="breakdown-scroll">' in html
    assert html.index('<div class="breakdown-scroll">') < html.index('<table class="breakdown-table">')
    css = Path("jobscanner/web/static/style.css").read_text()
    assert ".breakdown-scroll { overflow-x: auto; }" in css
    assert ".breakdown-table { width: 100%; border-collapse: collapse; margin-top: 0.5rem; font-size: 0.85rem; table-layout: fixed; min-width: 480px; }" in css


def test_breakdown_spans_full_card_width_outside_flex_column():
    html = Path("jobscanner/web/templates/dashboard.html").read_text()
    # Breakdown lives in a full-width wrapper at .job-card level, not inside the flex:1 title column
    assert '<div class="breakdown-full">' in html
    assert html.index('<div style="flex:1">') < html.index('<div class="breakdown-full">')
    assert html.index('data-vote-btn="down"') < html.index('<div class="breakdown-full">')
    css = Path("jobscanner/web/static/style.css").read_text()
    assert "flex-wrap: wrap;" in css
    assert ".breakdown-full { flex-basis: 100%; }" in css


def test_analyze_creates_analysis_and_launches_agent(client):
    pid = storage.get_profile_by_name("Tjark")["id"]
    with patch("jobscanner.web.app.subprocess.Popen") as popen:
        resp = client.post(f"/dashboard/{pid}/analyze", follow_redirects=False)
    assert resp.status_code == 303
    latest = storage.get_latest_analysis(pid)
    assert latest is not None and latest["status"] == "analyzing"
    args = popen.call_args[0][0]
    assert args[:3] == ["bash", "deploy/run_feedback_agent.sh", "analyze"]
    assert args[3] == str(latest["id"])


def test_analysis_get_returns_status_and_cards(client):
    pid = storage.get_profile_by_name("Tjark")["id"]
    aid = storage.create_analysis(pid)
    storage.save_analysis_cards(aid, {"up_muster": ["Remote"], "down_muster": [], "widersprüche": []})
    storage.set_analysis_status(aid, "pending_review")
    resp = client.get(f"/dashboard/{pid}/analysis")
    data = resp.json()
    assert data["status"] == "pending_review"
    assert data["cards"]["up_muster"] == ["Remote"]


def test_analysis_get_returns_none_status_when_no_analysis(client):
    pid = storage.get_profile_by_name("Tjark")["id"]
    resp = client.get(f"/dashboard/{pid}/analysis")
    assert resp.json()["status"] is None


def test_answers_route_saves_answers(client):
    pid = storage.get_profile_by_name("Tjark")["id"]
    aid = storage.create_analysis(pid)
    resp = client.post(f"/dashboard/{pid}/analysis/answers",
                       json={"analysis_id": aid, "answers": {"up_muster": [True]}},
                       follow_redirects=False)
    assert resp.status_code in (200, 303)
    assert storage.get_analysis(aid)["answers"] == {"up_muster": [True]}


def test_finalize_launches_synthesize_agent(client):
    pid = storage.get_profile_by_name("Tjark")["id"]
    aid = storage.create_analysis(pid)
    storage.set_analysis_status(aid, "pending_review")
    with patch("jobscanner.web.app.subprocess.Popen") as popen:
        resp = client.post(f"/dashboard/{pid}/finalize", follow_redirects=False)
    assert resp.status_code == 303
    assert storage.get_analysis(aid)["status"] == "synthesizing"
    args = popen.call_args[0][0]
    assert args[:3] == ["bash", "deploy/run_feedback_agent.sh", "synthesize"]
    assert args[3] == str(aid)


def test_confirm_insight_route_sets_confirmed(client):
    pid = storage.get_profile_by_name("Tjark")["id"]
    iid = storage.add_insight(pid, "preference", "Remote bevorzugt")
    resp = client.post(f"/dashboard/{pid}/insights/{iid}/confirm", follow_redirects=False)
    assert resp.status_code in (200, 303)
    assert storage.list_insights(pid, status="confirmed")[0]["id"] == iid


def test_reject_insight_route_sets_rejected(client):
    pid = storage.get_profile_by_name("Tjark")["id"]
    iid = storage.add_insight(pid, "preference", "irrelevant")
    resp = client.post(f"/dashboard/{pid}/insights/{iid}/reject", follow_redirects=False)
    assert resp.status_code in (200, 303)
    assert storage.list_insights(pid, status="rejected")[0]["id"] == iid


def test_apply_rescores_and_enqueues_when_preference_confirmed(client):
    pid = storage.get_profile_by_name("Tjark")["id"]
    fp = storage.upsert_job(Job(title="Unity Dev", company="ACME", location="Hamburg",
                                first_seen="2026-07-11"))
    storage.update_job(fp, score=50, category="Vielleicht")
    storage.confirm_insight(storage.add_insight(pid, "preference", "Hamburg stark"))
    with patch("jobscanner.web.app.subprocess.Popen") as popen:
        resp = client.post(f"/dashboard/{pid}/apply", follow_redirects=False)
    assert resp.status_code == 303
    # Präferenz vorhanden → bestehende Jobs enqueued (score genullt) + Scoring-Agent gestartet
    assert storage.get_job(fp).score is None
    assert popen.call_args[0][0][:2] == ["bash", "deploy/run_scoring_agent.sh"]


def test_apply_weight_only_does_not_launch_agent(client):
    pid = storage.get_profile_by_name("Tjark")["id"]
    storage.confirm_insight(storage.add_insight(
        pid, "weight", "", payload={"key": "location", "old_weight": 3, "new_weight": 5}))
    with patch("jobscanner.web.app.subprocess.Popen") as popen:
        resp = client.post(f"/dashboard/{pid}/apply", follow_redirects=False)
    assert resp.status_code == 303
    popen.assert_not_called()


def test_dashboard_has_lernen_tab(client):
    pid = storage.get_profile_by_name("Tjark")["id"]
    resp = client.get(f"/dashboard/{pid}")
    assert 'data-tab-target="lernen"' in resp.text
    assert "Votes analysieren" in resp.text


def test_dashboard_renders_pending_cards(client):
    pid = storage.get_profile_by_name("Tjark")["id"]
    aid = storage.create_analysis(pid)
    storage.save_analysis_cards(aid, {
        "up_muster": ["Remote + kleine Studios"], "down_muster": ["Senior onsite"],
        "widersprüche": [{"jobA": "A@HH", "jobB": "B@München", "frage": "warum?"}]})
    storage.set_analysis_status(aid, "pending_review")
    resp = client.get(f"/dashboard/{pid}")
    assert "Remote + kleine Studios" in resp.text
    assert "Senior onsite" in resp.text
    assert "Erkenntnisse finalisieren" in resp.text


def test_dashboard_renders_proposed_insights(client):
    pid = storage.get_profile_by_name("Tjark")["id"]
    storage.add_insight(pid, "preference", "Bevorzugt Remote + kleine Studios")
    storage.add_insight(pid, "weight", "",
                        payload={"key": "location", "old_weight": 3, "new_weight": 5})
    resp = client.get(f"/dashboard/{pid}")
    assert "Bevorzugt Remote + kleine Studios" in resp.text
    assert "Übernehmen &amp; Jobs neu bewerten" in resp.text or "Übernehmen & Jobs neu bewerten" in resp.text


@pytest.fixture
def member_client(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "geheim123")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@test.de")
    app = create_app(db_path=tmp_path / "jobs.db")
    c = CSRFTestClient(app)
    uid = storage.create_user("member@test.de", "memberpw", role="member")
    storage.mark_email_verified(uid)
    pid = storage.create_profile("Member-Profil", {"no_gos": []}, user_id=uid)
    storage.save_criteria(pid, [{"key": "remote", "label": "Remote", "weight": 5}])
    c.post("/login", data={"email": "member@test.de", "password": "memberpw"})
    return c, pid


class TestDashboardMemberLernen:
    def test_lernen_tab_visible_metriken_hidden(self, member_client):
        c, pid = member_client
        resp = c.get(f"/dashboard/{pid}")
        assert 'data-tab-target="lernen"' in resp.text
        assert "/metriken" not in resp.text

    def test_panel_is_read_only_no_analyze_or_confirm_form(self, member_client):
        c, pid = member_client
        resp = c.get(f"/dashboard/{pid}")
        assert "Votes analysieren" not in resp.text
        assert "/insights/" not in resp.text

    def test_reminder_badge_hidden_below_threshold(self, member_client):
        c, pid = member_client
        fp = storage.upsert_job(Job(title="Job A", company="ACME", location="Hamburg"))
        storage.add_feedback(pid, fp, "up")
        resp = c.get(f"/dashboard/{pid}")
        assert "Neue Analyse verfügbar" not in resp.text

    def test_reminder_badge_shown_at_threshold(self, member_client):
        c, pid = member_client
        for i in range(storage._LEARN_REMINDER_THRESHOLD):
            fp = storage.upsert_job(Job(title=f"Job {i}", company="ACME", location="Hamburg"))
            storage.add_feedback(pid, fp, "up")
        resp = c.get(f"/dashboard/{pid}")
        assert "Neue Analyse verfügbar" in resp.text

    def test_shows_confirmed_insights_without_reject_form(self, member_client):
        c, pid = member_client
        from jobscanner.web import mcp_api
        user = storage.get_user_by_email("member@test.de")
        mcp_api.apply_member_insights_data(
            user, pid, "preference", text="Bevorzugt Remote, aber Hamburg ok")
        resp = c.get(f"/dashboard/{pid}")
        assert "Bevorzugt Remote, aber Hamburg ok" in resp.text
        assert "entfernen" not in resp.text


def test_lernen_actions_redirect_to_lernen_tab(client):
    pid = storage.get_profile_by_name("Tjark")["id"]
    for path in (
        f"/dashboard/{pid}/apply",
        f"/dashboard/{pid}/insights/9999/confirm",
        f"/dashboard/{pid}/insights/9999/reject",
    ):
        resp = client.post(path, follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == f"/dashboard/{pid}#lernen", path


def _seed_scored(pid, n, *, prefix="Job", location="Hamburg", category="Pass"):
    """n eindeutig gefingerprintete, gescorte Jobs für pid anlegen."""
    for i in range(n):
        fp = storage.upsert_job(Job(title=f"{prefix} {i}", company=f"C{i}",
                                    location=location, first_seen="2026-07-11"))
        storage.upsert_job_score(pid, fp, 80, "", category, {})


def test_dashboard_slices_first_page_to_25(client):
    pid = storage.get_profile_by_name("Tjark")["id"]
    _seed_scored(pid, 30)
    resp = client.get(f"/dashboard/{pid}?tab=aktiv")
    assert resp.status_code == 200
    assert resp.text.count("data-fingerprint=") == 25


def test_dashboard_second_page_shows_remainder(client):
    pid = storage.get_profile_by_name("Tjark")["id"]
    _seed_scored(pid, 30)
    resp = client.get(f"/dashboard/{pid}?tab=aktiv&page=2")
    assert resp.status_code == 200
    assert resp.text.count("data-fingerprint=") == 5


def test_dashboard_clamps_too_large_page(client):
    pid = storage.get_profile_by_name("Tjark")["id"]
    _seed_scored(pid, 30)  # 2 Seiten
    resp = client.get(f"/dashboard/{pid}?tab=aktiv&page=99")
    assert resp.status_code == 200
    assert resp.text.count("data-fingerprint=") == 5  # auf letzte Seite geklemmt


def test_dashboard_remembers_page_per_tab(client):
    pid = storage.get_profile_by_name("Tjark")["id"]
    _seed_scored(pid, 30)
    client.get(f"/dashboard/{pid}?tab=aktiv&page=2")       # Seite merken
    resp = client.get(f"/dashboard/{pid}?tab=aktiv")        # ohne page → gemerkte Seite 2
    assert resp.text.count("data-fingerprint=") == 5


def test_dashboard_pages_are_independent_per_tab(client):
    pid = storage.get_profile_by_name("Tjark")["id"]
    _seed_scored(pid, 30, prefix="DE")                       # aktiv
    _seed_scored(pid, 30, prefix="US", location="New York")  # ausland
    client.get(f"/dashboard/{pid}?tab=aktiv&page=2")          # aktiv=Seite 2
    resp_ausland = client.get(f"/dashboard/{pid}?tab=ausland")  # ausland default Seite 1
    assert resp_ausland.text.count("data-fingerprint=") == 25
    resp_aktiv = client.get(f"/dashboard/{pid}?tab=aktiv")    # aktiv weiter Seite 2
    assert resp_aktiv.text.count("data-fingerprint=") == 5


def test_dashboard_counts_stay_full_despite_slicing(client):
    pid = storage.get_profile_by_name("Tjark")["id"]
    _seed_scored(pid, 30)
    resp = client.get(f"/dashboard/{pid}?tab=aktiv")
    assert resp.text.count("data-fingerprint=") == 25  # nur 25 gerendert
    assert "(30)" in resp.text                          # Count zeigt volle 30
