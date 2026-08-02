"""B1/B2/B4 — Render-Assertions für den UI-Refine-Batch."""
import pytest
from _csrf_client import CSRFTestClient

from jobscanner import storage
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


def test_topbar_hat_keinen_profilswitcher_mehr(client):
    html = client.get("/").text
    assert 'data-profile-switcher' not in html          # Switcher raus aus Topbar
    assert 'class="drawer-footer"' in html              # Email/Abmelden in Sidebar-Footer
    assert '/logout' in html                            # Abmelden bleibt erreichbar

def test_sidebar_tab_heisst_meine_profile(client):
    html = client.get("/").text
    assert "Meine Profile" in html
    assert ">Mein Profil<" not in html                  # altes Label weg

def test_profil_seite_titel_und_aktiv_setzen(client):
    uid = storage.get_user_by_email("owner@test.de")["id"]
    storage.create_profile("Zweitprofil", {"skills": []}, user_id=uid)  # nicht-aktiv
    html = client.get("/profil").text
    assert "Meine Profile" in html                      # H1/Title
    assert 'action="/profil/aktiv"' in html             # Aktiv-setzen-Formular umgezogen

def test_home_hat_banner(client):
    html = client.get("/").text
    assert "home-banner" in html
    assert "hero-landscape-band.png" in html

def test_export_button_in_filterzeile(client):
    html = client.get("/jobs?tab=aktiv").text
    # Export-Button steht in derselben .dash-filters-Zeile wie die Selects
    assert 'class="dash-filters"' in html
    filters = html.split('class="dash-filters"', 1)[1].split("</div>", 1)[0]
    assert 'name="sort"' in filters and 'name="min_score"' in filters
    assert 'export-trigger' in filters

def test_owner_wizard_seeded_25_kriterien(client):
    from jobscanner import scoring, storage
    before = {p["id"] for p in storage.list_profiles()}
    weights = {f"weight_{w['key']}": "3" for w in scoring.WEIGHTS_CATALOG}
    r = client.post("/wizard/gewichte", data=weights, follow_redirects=False)
    assert r.status_code == 303
    new = [p for p in storage.list_profiles() if p["id"] not in before]
    assert len(new) == 1
    assert len(storage.list_criteria(new[0]["id"])) == 25


def test_roadmap_route_zeigt_geplant_und_patches(client, tmp_path, monkeypatch):
    import json
    from jobscanner.web import app as appmod
    patches = {"patches": [
        {"version": "0.2.0", "date": "2026-07-29", "project": "job-scanner",
         "features": ["Feature Alpha"], "fixes": [], "member_notes": []},
        {"version": "9.9.9", "date": "2026-01-01", "project": "anderes-projekt",
         "features": ["Fremd-Feature"], "fixes": [], "member_notes": []},
    ]}
    pfile = tmp_path / "patches.json"
    pfile.write_text(json.dumps(patches), encoding="utf-8")
    monkeypatch.setattr(appmod, "PATCHES_JSON_PATH", pfile)

    html = client.get("/roadmap").text
    assert "Feature Alpha" in html                 # job-scanner-Patch sichtbar
    assert "Fremd-Feature" not in html             # anderes Projekt gefiltert
    assert "Bewerbungsassistent" in html           # geplante Liste (roadmap_planned.json)

def test_roadmap_ohne_patches_datei_ok(client, tmp_path, monkeypatch):
    from jobscanner.web import app as appmod
    monkeypatch.setattr(appmod, "PATCHES_JSON_PATH", tmp_path / "fehlt.json")
    r = client.get("/roadmap")
    assert r.status_code == 200                     # Leer-Zustand statt Fehler

def test_roadmap_in_sidebar(client):
    assert '/roadmap' in client.get("/").text


def test_brand_bob_ist_inline_block():
    from pathlib import Path
    css = Path("jobscanner/web/static/style.css").read_text(encoding="utf-8")
    assert ".brand .bob-avatar" in css
    regel = css.split(".brand .bob-avatar", 1)[1].split("}", 1)[0]
    assert "inline-block" in regel
    assert "28px" in regel
    # globale Regel bleibt Block
    assert ".bob-avatar { height: 64px; width: auto; display: block; }" in css


def test_topbar_bob_ohne_inline_style(client):
    html = client.get("/").text
    brand = html.split('class="brand"', 1)[1].split("</span>", 1)[0]
    assert "bob-pose-winken.png" in brand      # Bob bleibt in der Topbar
    assert "style=" not in brand               # Höhe kommt jetzt aus dem Stylesheet


def _drawer(client):
    """Nur die Sidebar aus dem gerenderten HTML — Home-Kacheln etc. bleiben außen vor."""
    html = client.get("/").text
    return html.split('<nav class="drawer', 1)[1].split("</nav>", 1)[0]


def test_sidebar_ohne_scan_eintrag(client):
    drawer = _drawer(client)
    assert 'href="/scan"' not in drawer
    assert "Scan starten" not in drawer


def test_sidebar_reihenfolge_suche_tunen(client):
    drawer = _drawer(client)
    for label in ("Meine Profile", "Feintuning", "Lern-Zentrum", "Portale prüfen"):
        assert label in drawer
    assert (drawer.index("Meine Profile") < drawer.index("Feintuning")
            < drawer.index("Lern-Zentrum") < drawer.index("Portale prüfen"))


def test_sidebar_lern_zentrum_umbenannt(client):
    drawer = _drawer(client)
    assert "Lern-Zentrum" in drawer
    assert ">Lernen<" not in drawer


def test_sidebar_reihenfolge_system(client):
    drawer = _drawer(client)
    assert "Roadmap/Patch Notes" in drawer
    assert "Patch notes" not in drawer          # altes kleines n weg
    assert drawer.index("Roadmap/Patch Notes") < drawer.index("Einstellungen")


def test_sidebar_meine_profile_vor_job_angebote(client):
    drawer = _drawer(client)
    # Profil steht jetzt in der Gruppe JOBS, als erster Eintrag über Job-Angebote
    assert drawer.index(">Jobs<") < drawer.index("Meine Profile") < drawer.index("Job-Angebote")
    assert drawer.index("Meine Profile") < drawer.index(">Suche tunen<")


def test_sidebar_icons_in_eigener_spalte(client):
    drawer = _drawer(client)
    for icon in ("⌂", "📋", "★", "🔔", "👤", "🎛", "🧠", "🌐", "🗺", "❓", "⚙", "📊", "🚪"):
        assert f'<span class="drawer-item-icon">{icon}</span>' in drawer, icon
    # kein nacktes Emoji mehr direkt vor dem Label
    assert '">⌂ <span class="drawer-item-label"' not in drawer


def test_sidebar_icon_spalte_css():
    from pathlib import Path
    css = Path("jobscanner/web/static/style.css").read_text(encoding="utf-8")

    item = css.split(".drawer-item {", 1)[1].split("}", 1)[0]
    assert "display: flex" in item
    assert "align-items: center" in item
    assert "gap: 0.5rem" in item

    icon = css.split(".drawer-item-icon {", 1)[1].split("}", 1)[0]
    assert "1.5rem" in icon
    assert "text-align: center" in icon

    # Gruppen-Überschriften auf derselben Textkante wie die Labels
    gruppe = css.split(".drawer-group {", 1)[1].split("}", 1)[0]
    assert "padding: 0 0.5rem 0 2.5rem" in gruppe

    # float wirkt auf ein Flex-Item nicht mehr -> Aufklapp-Pfeil braucht margin-left
    pfeil = css.split(".drawer-admin > summary::after {", 1)[1].split("}", 1)[0]
    assert "float" not in pfeil
    assert "margin-left: auto" in pfeil

    # eingeklappt (56px): nur Icons, zentriert
    assert ".drawer.drawer-collapsed .drawer-item { justify-content: center; }" in css


def test_banner_asset_zeigt_bob_und_schild():
    """1672x500-Crop aus hero-landscape-full.png — enthält Schild, Bob und den Pfad."""
    from pathlib import Path
    from PIL import Image
    band = Path("jobscanner/web/static/img/bob/hero-landscape-band.png")
    assert band.exists()
    assert Image.open(band).size == (1672, 500)
