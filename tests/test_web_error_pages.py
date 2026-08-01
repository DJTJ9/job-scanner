"""Globale HTML-Fehlerseiten (404/500) — API-Pfade und Accept: json bleiben JSON."""
import re

import pytest
from fastapi.testclient import TestClient

from jobscanner import storage
from jobscanner.web.app import create_app
from _csrf_client import CSRFTestClient


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "geheim123")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@test.de")
    return create_app(db_path=tmp_path / "jobs.db")


def test_404_page_renders_html(app):
    resp = TestClient(app).get("/gibt-es-nicht")
    assert resp.status_code == 404
    assert "text/html" in resp.headers["content-type"]
    assert "Seite nicht gefunden" in resp.text


def test_404_api_path_stays_json(app):
    resp = TestClient(app).get("/api/gibt-es-nicht")
    assert resp.status_code == 404
    assert "application/json" in resp.headers["content-type"]


def test_404_accept_json_stays_json(app):
    resp = TestClient(app).get("/gibt-es-nicht", headers={"accept": "application/json"})
    assert resp.status_code == 404
    assert "application/json" in resp.headers["content-type"]


def test_500_page_renders_html_no_stacktrace(app, monkeypatch):
    login = CSRFTestClient(app)
    resp = login.post("/login", data={"email": "owner@test.de", "password": "geheim123"})
    assert resp.status_code in (200, 303)

    def boom(*args, **kwargs):
        raise RuntimeError("kaboom-secret")

    monkeypatch.setattr(storage, "get_home_summary", boom)

    client = TestClient(app, raise_server_exceptions=False)
    client.cookies.update(login.cookies)
    resp = client.get("/", headers={"accept": "text/html"})
    assert resp.status_code == 500
    assert "text/html" in resp.headers["content-type"]
    assert "schiefgelaufen" in resp.text
    assert "kaboom-secret" not in resp.text


def test_error_page_bild_ist_eine_ganze_figur(app):
    """Das Bild der Fehlerseite muss eine echte Bob-Figur sein.

    Die `bob-emotion-*.png` sind 116x55 grosse Sprite-Paare (Augen/Mund) — auf
    die 140px der `.error-bob`-Regel gezogen sehen sie aus wie ein kaputtes Icon.
    """
    from pathlib import Path

    from PIL import Image

    resp = TestClient(app).get("/gibt-es-nicht")
    treffer = re.search(r'class="error-bob" src="(/static/[^"?]+)"', resp.text)
    assert treffer, "Fehlerseite ohne error-bob-Bild"
    datei = Path("jobscanner/web/static") / treffer.group(1)[len("/static/"):]
    assert datei.exists(), datei
    assert Image.open(datei).size[1] >= 100, "Sprite-Fragment statt ganzer Figur"


def test_500_seite_nennt_ursache_und_naechsten_schritt(app, monkeypatch):
    login = CSRFTestClient(app)
    login.post("/login", data={"email": "owner@test.de", "password": "geheim123"})

    def boom(*args, **kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(storage, "get_home_summary", boom)
    client = TestClient(app, raise_server_exceptions=False)
    client.cookies.update(login.cookies)
    resp = client.get("/", headers={"accept": "text/html"})

    assert resp.status_code == 500
    assert "nicht an dir" in resp.text          # sagt, wer schuld ist
    assert "noch einmal" in resp.text           # sagt, was man tun kann


def test_verify_invalid_token_renders_html(app):
    from fastapi.testclient import TestClient
    client = TestClient(app)
    resp = client.get("/verify-email?token=ungueltig", follow_redirects=False)
    assert resp.status_code == 404
    assert "text/html" in resp.headers["content-type"]
    assert "Verifizierungs-Link" in resp.text


def test_csrf_fail_fullpage_form_renders_html(app):
    resp = TestClient(app).post(
        "/login",
        data={"email": "owner@test.de", "password": "x"},
        follow_redirects=False,
    )
    assert resp.status_code == 403
    assert "text/html" in resp.headers["content-type"]
    assert "Sicherheits-Token" in resp.text


def test_csrf_fail_ajax_endpoint_stays_json(app):
    resp = TestClient(app).post(
        "/api/feedback",
        data={"raw_job_id": "1", "verdict": "up"},
        follow_redirects=False,
    )
    assert resp.status_code == 403
    assert "text/html" not in resp.headers.get("content-type", "")


def _owner_cookies(app):
    login = CSRFTestClient(app)
    resp = login.post(
        "/login",
        data={"email": "owner@test.de", "password": "geheim123"},
        follow_redirects=False,
    )
    assert resp.status_code in (200, 303)
    raw = TestClient(app)
    raw.cookies.update(login.cookies)
    return raw


def test_csrf_fail_criteria_form_renders_html(app):
    raw = _owner_cookies(app)
    pid = storage.get_profile_by_name("Tjark")["id"]
    resp = raw.post(f"/dashboard/{pid}/criteria", data={}, follow_redirects=False)
    assert resp.status_code == 403
    assert "text/html" in resp.headers["content-type"]
    assert "Sicherheits-Token" in resp.text


def test_csrf_fail_admin_member_form_renders_html(app):
    raw = _owner_cookies(app)
    resp = raw.post("/admin/members/1/verify", data={}, follow_redirects=False)
    assert resp.status_code == 403
    assert "text/html" in resp.headers["content-type"]
    assert "Sicherheits-Token" in resp.text


def test_csrf_fail_wizard_step_renders_html(app):
    raw = _owner_cookies(app)
    resp = raw.post("/wizard/basis", data={"name": "X"}, follow_redirects=False)
    assert resp.status_code == 403
    assert "text/html" in resp.headers["content-type"]
    assert "Sicherheits-Token" in resp.text


def test_csrf_fail_settings_save_stays_json(app):
    # data-confirm-save-fetch-Form: bleibt per Spec-Ausnahme JSON
    raw = _owner_cookies(app)
    resp = raw.post("/einstellungen/notify", data={}, follow_redirects=False)
    assert resp.status_code == 403
    assert "text/html" not in resp.headers.get("content-type", "")


def test_csrf_fail_authed_fullpage_stays_html(app):
    login = CSRFTestClient(app)
    resp = login.post(
        "/login",
        data={"email": "owner@test.de", "password": "geheim123"},
        follow_redirects=False,
    )
    assert resp.status_code in (200, 303)
    raw = TestClient(app)
    raw.cookies.update(login.cookies)
    resp = raw.post(
        "/account/passwort",
        data={
            "current_password": "geheim123",
            "new_password": "neuespw123",
            "new_password_repeat": "neuespw123",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 403
    assert "text/html" in resp.headers["content-type"]
    assert "Sicherheits-Token" in resp.text
