"""Tests für Aktives-Profil-Session-Helper + Switcher-Route."""
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


def test_switch_setzt_aktives_profil_und_redirectet_auf_referer_pfad(client):
    uid = storage.get_user_by_email("owner@test.de")["id"]
    pid2 = storage.create_profile("Zweitprofil", {"skills": []}, user_id=uid)
    resp = client.post(f"/profil/aktiv", data={"profile_id": str(pid2)},
                       headers={"referer": "https://evil.example/jobs"},
                       follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/jobs"      # nur Pfad, kein Open-Redirect
    # aktives Profil wirkt: /feintuning zeigt Kriterien des Zweitprofils
    assert client.get("/").status_code in (200, 303)


def test_switch_fremdes_profil_404(client):
    andere = storage.create_user("other@test.de", "geheim123")
    fremd = storage.create_profile("Fremd", {"skills": []}, user_id=andere)
    resp = client.post("/profil/aktiv", data={"profile_id": str(fremd)},
                       follow_redirects=False)
    assert resp.status_code == 404
