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
