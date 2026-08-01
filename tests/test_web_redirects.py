"""Tests für 301-Redirects der Alt-URLs (Bookmark-Stabilität)."""
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


def _pid():
    return storage.get_profile_by_name("Tjark")["id"]


@pytest.mark.parametrize("tab,ziel", [
    ("aktiv", "/jobs?tab=aktiv"),
    ("no_go", "/jobs?tab=no_go"),
    ("bewertet", "/jobs?tab=bewertet"),
    ("ausland", "/jobs?tab=ausland"),
])
def test_dashboard_tab_301(client, tab, ziel):
    resp = client.get(f"/dashboard/{_pid()}?tab={tab}", follow_redirects=False)
    assert resp.status_code == 301
    assert resp.headers["location"] == ziel


def test_dashboard_ohne_tab_301_auf_jobs(client):
    resp = client.get(f"/dashboard/{_pid()}", follow_redirects=False)
    assert resp.status_code == 301
    assert resp.headers["location"] == "/jobs"


def test_dashboard_metriken_301(client):
    resp = client.get(f"/dashboard/{_pid()}/metriken", follow_redirects=False)
    assert resp.status_code == 301
    assert resp.headers["location"] == "/metriken"


def test_dashboard_redirect_setzt_aktives_profil_wenn_eigenes(client):
    uid = storage.get_user_by_email("owner@test.de")["id"]
    pid2 = storage.create_profile("Zweit", {"skills": []}, user_id=uid)
    client.get(f"/dashboard/{pid2}", follow_redirects=False)
    resp = client.get("/profil")
    assert 'class="panel profile-card is-active"' in resp.text   # eine Karte ist aktiv
    assert f'value="{pid2}"' not in resp.text                    # Zweit: kein Wechsel-Button
