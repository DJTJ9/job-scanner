"""Member-Onboarding-Anleitung: profile_exists-Flag, Buttons/Partials, CSS/JS-Reuse."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jobscanner import storage
from jobscanner.web.app import create_app


@pytest.fixture
def owner_client(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "geheim123")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@test.de")
    app = create_app(db_path=tmp_path / "jobs.db")
    c = TestClient(app)
    c.post("/login", data={"email": "owner@test.de", "password": "geheim123"})
    return c


@pytest.fixture
def member_client(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "geheim123")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@test.de")
    app = create_app(db_path=tmp_path / "jobs.db")
    storage.create_user("member@test.de", "pw", role="member")
    c = TestClient(app)
    c.post("/login", data={"email": "member@test.de", "password": "pw"})
    return c


def test_profile_exists_true_for_owner_with_migrated_profile(owner_client):
    resp = owner_client.get("/")
    assert 'data-profile-exists="true"' in resp.text


def test_profile_exists_false_for_member_without_profile(member_client):
    resp = member_client.get("/")
    assert 'data-profile-exists="false"' in resp.text


def test_hero_buttons_render_when_no_profile(member_client):
    resp = member_client.get("/")
    assert "onboarding-hero" in resp.text
    assert 'data-onboarding-open="onboarding-bot"' in resp.text
    assert 'data-onboarding-open="onboarding-was-kann"' in resp.text
    assert 'data-onboarding-open="onboarding-wizard"' in resp.text
    assert "🤖 Wer bin ich?" in resp.text
    assert "💡 Was kann ich?" in resp.text
    assert "📋 Wer bist du?" in resp.text


def test_corner_icons_render_when_profile_exists_not_hero(owner_client):
    resp = owner_client.get("/")
    assert "onboarding-corner" in resp.text
    assert "onboarding-hero" not in resp.text


def test_onboarding_panels_hidden_by_default_and_wizard_links_to_new(member_client):
    resp = member_client.get("/")
    assert 'id="onboarding-bot" class="panel onboarding-panel panel-hidden"' in resp.text
    assert 'id="onboarding-wizard" class="panel onboarding-panel panel-hidden"' in resp.text
    assert 'href="/wizard/new"' in resp.text
    assert 'data-onboarding-close="onboarding-bot"' in resp.text
    assert 'data-onboarding-close="onboarding-wizard"' in resp.text


def test_onboarding_css_classes_present_and_reuse_theme():
    css = Path("jobscanner/web/static/style.css").read_text()
    for cls in (".onboarding-hero", ".onboarding-header", ".onboarding-corner",
                ".onboarding-icon-btn", ".onboarding-panel", ".onboarding-avatar-wrap"):
        assert cls in css
    assert "var(--signal)" in css.split(".onboarding-icon-btn")[1].split("}")[0]


def test_onboarding_css_reuses_ping_keyframes_only():
    css = Path("jobscanner/web/static/style.css").read_text()
    assert css.count("@keyframes") == 1   # nur ping-pulse — keine neue Animation


def test_app_js_has_onboarding_toggle_snippet():
    js = Path("jobscanner/web/static/app.js").read_text()
    assert 'data-onboarding-open' in js
    assert 'data-onboarding-close' in js
    assert 'panel-hidden' in js


def test_bot_panel_has_portfolio_framing_and_tech_stack_chips(member_client):
    resp = member_client.get("/")
    assert "Portfolio-Projekt" in resp.text
    for tech in ("Python", "FastAPI", "Jinja2", "SQLite", "Playwright", "Firecrawl",
                 "Groq", "Claude Agents", "systemd", "NocoDB", "Caddy"):
        assert f'<span class="chip">{tech}</span>' in resp.text


def test_bot_panel_trigger_link_opens_lesson_panel(member_client):
    resp = member_client.get("/")
    assert 'data-onboarding-open="onboarding-lesson"' in resp.text
    assert "Wie das genau funktioniert" in resp.text


def test_lesson_panel_renders_hidden_with_full_tour(member_client):
    resp = member_client.get("/")
    assert 'id="onboarding-lesson" class="panel onboarding-panel panel-hidden"' in resp.text
    for step in ("Ingestion", "Extraktion", "Storage", "Scoring", "Dashboard", "Feedback-Loop"):
        assert step in resp.text
    assert 'data-onboarding-close="onboarding-lesson"' in resp.text


def test_lesson_panel_links_to_external_teach_lesson(member_client):
    resp = member_client.get("/")
    assert 'href="https://djtj9.github.io/teach-lessons/job-scanner/job-scanner-erklaert/lessons/job-scanner-erklaert.html"' in resp.text
    assert 'target="_blank"' in resp.text


def test_bot_panel_last_paragraph_has_no_employer_address(member_client):
    resp = member_client.get("/")
    assert "Für dich heißt das: weniger Zeit mit manuellem Suchen, mehr passende Treffer." in resp.text
    assert "Bewerber" not in resp.text
    assert "selbst gerade" not in resp.text


def test_lesson_panel_heading_has_der(member_client):
    resp = member_client.get("/")
    assert "Wie Bob der Job-Bot funktioniert" in resp.text
    assert "<h2>Wie Job-Scanner funktioniert</h2>" not in resp.text


def test_app_js_closes_all_onboarding_panels_before_opening_target():
    js = Path("jobscanner/web/static/app.js").read_text()
    open_block = js.split('querySelectorAll("[data-onboarding-open]")')[1].split("});")[0]
    assert 'querySelectorAll(".onboarding-panel")' in open_block
    close_all_pos = open_block.index('querySelectorAll(".onboarding-panel")')
    open_target_pos = open_block.index('classList.remove("panel-hidden")')
    assert close_all_pos < open_target_pos


def test_bot_panel_mentions_aussortiert_in_profil(member_client):
    resp = member_client.get("/")
    assert "Aussortiert" in resp.text
    assert "filtere ich automatisch raus" in resp.text


def test_dashboard_renames_tabs_to_jobangebote_and_aussortiert(owner_client):
    pid = storage.list_profiles(user_id=1)[0]["id"]
    resp = owner_client.get(f"/dashboard/{pid}")
    # Top-Tab + Panel-Überschrift umbenannt, Query-Param/ID unverändert
    assert 'data-tab-target="kontakte">Job-Angebote' in resp.text
    assert "<h2>Job-Angebote</h2>" in resp.text
    # Top-Tab-Label No-Go → Aussortiert (Link-Target ?tab=no_go bleibt)
    assert '?tab=no_go">Aussortiert' in resp.text


def test_wizard_panel_shows_function_overview_and_two_buttons(member_client):
    resp = member_client.get("/")
    # id + panel-Klassen + Close bleiben erhalten (bestehende Tests hängen daran)
    assert 'id="onboarding-wizard" class="panel onboarding-panel panel-hidden"' in resp.text
    assert 'data-onboarding-close="onboarding-wizard"' in resp.text
    # neuer Funktions-Überblick + zwei Buttons
    assert "Alle Funktionen im Detail" in resp.text
    assert 'data-onboarding-open="onboarding-guide"' in resp.text
    assert 'href="/wizard/new"' in resp.text
    assert "Profil erstellen" in resp.text


def test_guide_panel_renders_hidden_and_links_to_teach_lesson(member_client):
    resp = member_client.get("/")
    assert 'id="onboarding-guide" class="panel onboarding-panel panel-hidden"' in resp.text
    assert "job-scanner-nutzen/lessons/job-scanner-nutzen.html" in resp.text
    assert 'data-onboarding-close="onboarding-guide"' in resp.text


def test_hero_wizard_button_uses_clipboard_icon(member_client):
    resp = member_client.get("/")
    assert "📋 Wer bist du?" in resp.text
    assert "🧭" not in resp.text  # altes Icon vollständig ersetzt (Hero + Corner)


def test_hero_buttons_have_filled_color_rules():
    css = Path("jobscanner/web/static/style.css").read_text(encoding="utf-8")
    assert '.onboarding-hero .btn[data-onboarding-open="onboarding-bot"]' in css
    assert '.onboarding-hero .btn[data-onboarding-open="onboarding-wizard"]' in css
    assert "var(--beute)" in css
    assert "var(--signal)" in css


def test_drawer_and_panels_present_on_non_home_page(owner_client):
    pid = storage.list_profiles(user_id=1)[0]["id"]
    resp = owner_client.get(f"/dashboard/{pid}")
    assert "data-drawer-open" in resp.text
    assert '<a class="drawer-item" href="/">' in resp.text
    assert 'id="onboarding-bot" class="panel onboarding-panel panel-hidden"' in resp.text
    assert 'id="onboarding-was-kann" class="panel onboarding-panel panel-hidden"' in resp.text
    assert 'id="onboarding-wizard" class="panel onboarding-panel panel-hidden"' in resp.text


def test_was_kann_panel_has_function_overview(member_client):
    resp = member_client.get("/")
    assert 'id="onboarding-was-kann" class="panel onboarding-panel panel-hidden"' in resp.text
    assert "Alle Funktionen im Detail" in resp.text
    assert 'data-onboarding-open="onboarding-guide"' in resp.text
    assert 'data-onboarding-close="onboarding-was-kann"' in resp.text


def test_wizard_panel_trimmed_to_profile_start(member_client):
    resp = member_client.get("/")
    assert 'id="onboarding-wizard" class="panel onboarding-panel panel-hidden"' in resp.text
    assert 'href="/wizard/new"' in resp.text
    assert "Profil erstellen" in resp.text
    wizard_block = resp.text.split('id="onboarding-wizard"')[1].split("</div>")[0]
    assert "👍/👎 Jobs bewerten" not in wizard_block


def test_app_js_has_drawer_toggle():
    js = Path("jobscanner/web/static/app.js").read_text()
    assert "data-drawer-open" in js
    assert "data-drawer-close" in js
    assert 'getElementById("drawer")' in js


def test_drawer_and_panels_absent_pre_auth():
    import os
    from fastapi.testclient import TestClient
    from jobscanner.web.app import create_app
    os.environ.setdefault("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    client = TestClient(create_app(db_path="/tmp/na_preauth.db"))
    resp = client.get("/login")
    assert "data-drawer-open" not in resp.text
    assert 'id="onboarding-bot"' not in resp.text


def test_hero_has_three_equal_onboarding_buttons(member_client):
    resp = member_client.get("/")
    assert "onboarding-hero" in resp.text
    assert 'data-onboarding-open="onboarding-bot">🤖 Wer bin ich?' in resp.text
    assert 'data-onboarding-open="onboarding-was-kann">💡 Was kann ich?' in resp.text
    assert 'data-onboarding-open="onboarding-wizard">📋 Wer bist du?' in resp.text


def test_corner_has_three_onboarding_icons(owner_client):
    resp = owner_client.get("/")
    assert "onboarding-corner" in resp.text
    assert 'data-onboarding-open="onboarding-bot"' in resp.text
    assert 'data-onboarding-open="onboarding-was-kann"' in resp.text
    assert 'data-onboarding-open="onboarding-wizard"' in resp.text


def test_hero_grid_is_three_equal_columns():
    css = Path("jobscanner/web/static/style.css").read_text()
    hero_rule = css.split(".onboarding-hero {")[1].split("}")[0]
    assert "grid-template-columns: repeat(3, 1fr)" in hero_rule


def test_wizard_step_two_has_back_link_to_previous(owner_client):
    resp = owner_client.get("/wizard/skills")
    assert 'href="/wizard/basis">← Zurück' in resp.text


def test_wizard_first_step_has_no_back_link(owner_client):
    resp = owner_client.get("/wizard/basis")
    assert "← Zurück" not in resp.text


def test_wizard_has_cancel_to_home(owner_client):
    resp = owner_client.get("/wizard/basis")
    assert 'href="/">Abbrechen → Startseite' in resp.text
