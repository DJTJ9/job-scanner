"""Tests für Home-Übersicht (/) und ausgeloggte Landing."""
import pytest
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
    return CSRFTestClient(app)


def _login(client):
    client.post("/login", data={"email": "owner@test.de", "password": "geheim123"})


def test_ausgeloggt_zeigt_landing_statt_login_redirect(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 200
    assert "Anmelden" in resp.text


def test_eingeloggt_zeigt_sonar_uebersicht(client):
    _login(client)
    pid = storage.get_profile_by_name("Tjark")["id"]
    fp = storage.upsert_job(Job(title="Top Dev", company="ACME", location="Hamburg",
                                first_seen="2026-07-27"))
    storage.upsert_job_score(pid, fp, 95, "top", "Pass", {})
    storage.log_event("scan_pushed", meta={"source": "server"})
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Letzter Scan" in resp.text
    assert "neue Treffer" in resp.text
    assert "Top Dev" in resp.text            # Top-Treffer-Widget


def test_home_markiert_nichts_als_notified(client):
    _login(client)
    pid = storage.get_profile_by_name("Tjark")["id"]
    fp = storage.upsert_job(Job(title="X", company="Y", location="Z",
                                first_seen="2026-07-27"))
    storage.upsert_job_score(pid, fp, 90, "g", "Pass", {})
    client.get("/")
    assert len(storage.list_unnotified_top_matches(pid)) == 1


def test_naechste_schritte_bleiben_sichtbar_wenn_erledigt(client):
    _login(client)
    pid = storage.get_profile_by_name("Tjark")["id"]
    resp = client.get("/")
    assert "Nächste Schritte" in resp.text   # keine 5 Votes
    for i in range(5):
        fp = storage.upsert_job(Job(title=f"J{i}", company=f"C{i}", location="HH",
                                    first_seen="2026-07-27"))
        storage.add_feedback(pid, fp, "up")
    resp = client.get("/")
    assert "Nächste Schritte" in resp.text


def test_wizard_abschluss_redirectet_auf_home(client):
    _login(client)
    client.get("/wizard/new")
    for step, data in [("basis", {"name": "Neu", "level": "senior", "experience_years": "5"}),
                       ("skills", {"skills": "unity"}),
                       ("zielrollen", {"target_roles": "dev"}),
                       ("domaenen", {}),
                       ("ort_umfang", {"cities": "HH"}),
                       ("no_gos", {})]:
        client.post(f"/wizard/{step}", data=data)
    resp = client.post("/wizard/gewichte", data={}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
