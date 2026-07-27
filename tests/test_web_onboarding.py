"""Command-Center-Startseite, gebündelte /onboarding-Seite, Panel-Overflow-Fix (.safe-sheet)."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from _csrf_client import CSRFTestClient

from jobscanner import storage
from jobscanner.web.app import create_app


@pytest.fixture
def owner_client(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "geheim123")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@test.de")
    app = create_app(db_path=tmp_path / "jobs.db")
    c = CSRFTestClient(app)
    c.post("/login", data={"email": "owner@test.de", "password": "geheim123"})
    return c


@pytest.fixture
def member_client(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "geheim123")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@test.de")
    app = create_app(db_path=tmp_path / "jobs.db")
    uid = storage.create_user("member@test.de", "pw", role="member")
    storage.mark_email_verified(uid)
    c = CSRFTestClient(app)
    c.post("/login", data={"email": "member@test.de", "password": "pw"})
    return c


# --- /onboarding → Hilfe-Center ---

def test_onboarding_redirects_301_to_hilfe():
    import os
    os.environ.setdefault("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    client = TestClient(create_app(db_path="/tmp/na_onboarding_preauth.db"))
    resp = client.get("/onboarding", follow_redirects=False)
    assert resp.status_code == 301
    assert resp.headers["location"] == "/hilfe#erste-schritte"


def test_onboarding_sections_on_hilfe_in_order(member_client):
    resp = member_client.get("/hilfe")
    assert resp.status_code == 200
    text = resp.text
    positions = [text.index(h) for h in (
        "Wer bin ich?", "Wer bist du?", "Wie kannst du mitmachen?",
        "Was kann ich?", "Wie ich arbeite")]
    assert positions == sorted(positions)


def test_onboarding_mitmachen_panel_content(member_client):
    text = member_client.get("/hilfe").text
    assert "Invite" in text
    assert "Heim-IP" in text
    assert 'href="#anleitung">Zur Anleitung' in text
    assert "/static/img/bob/bob-pose-daumen-hoch.png" in text


def test_onboarding_page_keeps_bot_avatar_images(member_client):
    resp = member_client.get("/hilfe")
    assert "/static/img/bob/bob-pose-rakete.png" in resp.text
    assert "/static/img/bob/bob-pose-herz.png" in resp.text
    assert "/static/img/bob/bob-pose-frage.png" in resp.text


def test_onboarding_page_wizard_section_links_to_new_profile(member_client):
    resp = member_client.get("/hilfe")
    assert 'href="/wizard/new"' in resp.text
    assert "Profil erstellen" in resp.text


def test_onboarding_page_links_to_setup_anleitung(member_client):
    resp = member_client.get("/hilfe")
    assert 'href="#anleitung">Setup-Anleitung' in resp.text


def test_onboarding_page_mentions_aussortiert(member_client):
    resp = member_client.get("/hilfe")
    assert "Aussortiert" in resp.text
    assert "filtere ich automatisch raus" in resp.text


def test_onboarding_page_has_tech_stack_chips(member_client):
    resp = member_client.get("/hilfe")
    for tech in ("Python", "FastAPI", "Jinja2", "SQLite", "Playwright", "Firecrawl",
                 "Claude", "Claude Agents", "systemd", "NocoDB", "Caddy"):
        assert f'<span class="chip">{tech}</span>' in resp.text


def test_onboarding_partials_deleted():
    for name in ("_onboarding_bot.html", "_onboarding_was_kann.html",
                 "_onboarding_wizard.html", "_onboarding_lesson.html"):
        assert not Path(f"jobscanner/web/templates/{name}").exists()


# --- Command-Center-Startseite ---

def test_erstbesuch_banner_links_to_onboarding_instead_of_hero_buttons(member_client):
    resp = member_client.get("/")
    assert "onboarding-hero" not in resp.text
    assert 'data-onboarding-open="onboarding-bot"' not in resp.text
    assert 'href="/onboarding"' in resp.text
    assert "Neu hier?" in resp.text


def test_command_center_shows_three_cards_for_existing_profile(owner_client):
    resp = owner_client.get("/")
    assert 'class="cc-grid"' in resp.text
    assert "Scan starten" in resp.text
    assert "Ergebnisse" in resp.text
    assert "Feedback geben" in resp.text
    assert "Profil pflegen" not in resp.text


def test_command_center_cards_link_to_existing_routes(owner_client):
    pid = storage.list_profiles(user_id=1)[0]["id"]
    resp = owner_client.get("/")
    assert 'href="/einstellungen?tab=token"' in resp.text
    assert f'href="/dashboard/{pid}#kontakte"' in resp.text
    assert f'href="/wizard/edit/{pid}"' in resp.text
    assert "data-feedback-toggle" in resp.text


def test_command_center_no_welcome_banner(owner_client):
    resp = owner_client.get("/")
    assert "Willkommen zurück" not in resp.text
    assert "cc-hero" not in resp.text


def test_command_center_shows_new_matches_in_results_card(owner_client):
    from jobscanner.models import Job
    pid = storage.list_profiles(user_id=1)[0]["id"]
    fp = storage.upsert_job(Job(title="Unity Dev", company="ACME", location="Hamburg",
                                first_seen="2026-07-11"))
    storage.upsert_job_score(pid, fp, 90, "Pass", "Pass", {})
    resp = owner_client.get("/")
    assert "Ergebnisse (1)" in resp.text


def test_profile_list_still_present_below_command_center(owner_client):
    resp = owner_client.get("/")
    assert 'data-profile-exists="true"' in resp.text
    assert "<h2>Profile</h2>" in resp.text


# --- base.html / Drawer ---

def test_drawer_has_single_onboarding_link_not_three_buttons(owner_client):
    pid = storage.list_profiles(user_id=1)[0]["id"]
    resp = owner_client.get(f"/dashboard/{pid}")
    assert '<a class="drawer-item" href="/onboarding">' in resp.text
    assert 'data-onboarding-open="onboarding-bot"' not in resp.text
    assert 'data-onboarding-open="onboarding-was-kann"' not in resp.text
    assert 'data-onboarding-open="onboarding-wizard"' not in resp.text


def test_base_no_longer_includes_onboarding_panels(owner_client):
    pid = storage.list_profiles(user_id=1)[0]["id"]
    resp = owner_client.get(f"/dashboard/{pid}")
    assert 'id="onboarding-bot"' not in resp.text
    assert 'id="onboarding-was-kann"' not in resp.text
    assert 'id="onboarding-wizard"' not in resp.text
    assert 'id="onboarding-lesson"' not in resp.text


def test_drawer_and_panels_absent_pre_auth():
    import os
    os.environ.setdefault("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    client = TestClient(create_app(db_path="/tmp/na_preauth.db"))
    resp = client.get("/login")
    assert "data-drawer-open" not in resp.text
    assert 'id="onboarding-bot"' not in resp.text


def test_app_js_has_drawer_toggle():
    js = Path("jobscanner/web/static/app.js").read_text()
    assert "data-drawer-open" in js
    assert "data-drawer-close" in js
    assert 'getElementById("drawer")' in js


# --- .safe-sheet Panel-Fix ---

def test_feedback_panel_has_safe_sheet_class(owner_client):
    pid = storage.list_profiles(user_id=1)[0]["id"]
    resp = owner_client.get(f"/dashboard/{pid}")
    assert 'class="panel feedback-panel safe-sheet panel-hidden"' in resp.text


def test_feedback_panel_close_button_before_body_in_markup(owner_client):
    pid = storage.list_profiles(user_id=1)[0]["id"]
    resp = owner_client.get(f"/dashboard/{pid}")
    assert resp.text.index('data-feedback-close') < resp.text.index('feedback-panel-body')


def test_safe_sheet_css_defined():
    css = Path("jobscanner/web/static/style.css").read_text()
    assert ".safe-sheet {" in css
    safe_sheet_rule = css.split(".safe-sheet {")[1].split("}")[0]
    assert "overflow-y: auto" in safe_sheet_rule
    assert "max-height:" in safe_sheet_rule


def test_feedback_panel_close_uses_sticky_positioning():
    css = Path("jobscanner/web/static/style.css").read_text()
    close_rule = css.split(".feedback-panel-close {")[1].split("}")[0]
    assert "position: sticky" in close_rule


def test_onboarding_dead_css_removed():
    css = Path("jobscanner/web/static/style.css").read_text()
    assert ".onboarding-hero {" not in css
    assert ".onboarding-panel {" not in css


def test_onboarding_css_reuses_ping_keyframes_only():
    css = Path("jobscanner/web/static/style.css").read_text()
    assert css.count("@keyframes") == 2   # ping-pulse + feedback-fab-pulse (Sag's-Bob-Widget)


# --- Unabhängig von diesem Feature, unverändert übernommen ---

def test_dashboard_renames_tabs_to_jobangebote_and_aussortiert(owner_client):
    pid = storage.list_profiles(user_id=1)[0]["id"]
    resp = owner_client.get(f"/dashboard/{pid}")
    assert 'data-tab-target="kontakte">Job-Angebote' in resp.text
    assert "<h2>Job-Angebote</h2>" in resp.text
    assert '?tab=no_go">Aussortiert' in resp.text


def test_wizard_step_two_has_back_link_to_previous(owner_client):
    resp = owner_client.get("/wizard/skills")
    assert 'href="/wizard/basis">← Zurück' in resp.text


def test_wizard_first_step_has_no_back_link(owner_client):
    resp = owner_client.get("/wizard/basis")
    assert "← Zurück" not in resp.text


def test_wizard_has_cancel_to_home(owner_client):
    resp = owner_client.get("/wizard/basis")
    assert 'Abbrechen' in resp.text
    assert '→ Startseite' not in resp.text


# --- .hinweis-Klasse vereinheitlicht ---

def test_settings_hint_texts_use_hinweis_class(owner_client):
    resp = owner_client.get("/einstellungen?tab=token")
    assert '<p class="hinweis">' in resp.text
    assert resp.text.count('<p class="hinweis">') >= 2  # Spar-Modus + Portal-Auswahl


def test_portale_beispiel_uses_hinweis_class(owner_client):
    resp = owner_client.get("/portale")
    assert 'class="hinweis"' in resp.text
    assert "z.B. https://bar.de/jobs?q={query}" in resp.text


def test_keys_hint_box_uses_hinweis_class(owner_client):
    resp = owner_client.get("/anleitung/keys")
    assert 'class="anl-shot-hinweis hinweis"' in resp.text


def test_hinweis_class_is_unscoped_in_css():
    css = Path("jobscanner/web/static/style.css").read_text()
    assert ".logbuch .hinweis" not in css
    assert ".hinweis {" in css


def test_datenschutz_hinweis_still_renders(owner_client):
    resp = owner_client.get("/datenschutz")
    assert 'class="hinweis"' in resp.text
