"""B1/B2/B4 — Render-Assertions für den UI-Refine-Batch."""
import pytest
from _csrf_client import CSRFTestClient

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
