"""Bug-Audit-Statusmatrix über alle Member-GET-Routen (Admin ausgeschlossen).
Deterministischer Regressions-Smoke: fängt 500er, ungerenderte Templates,
kaputte interne Links flächendeckend ab."""
import re

import pytest
from _csrf_client import CSRFTestClient

from jobscanner import storage
from jobscanner.web.app import create_app

ERROR_MARKERS = ("Traceback (most recent call last)", "Internal Server Error")

# Voll gerenderte Content-Seiten: erwartet 200 + keine Fehler-Marker.
CONTENT_ROUTES = [
    "/impressum", "/datenschutz", "/anleitung", "/anleitung/keys", "/anleitung/scan",
    "/hilfe", "/hilfe/handbuch", "/onboarding", "/account/passwort", "/account/username",
    "/account/email", "/einstellungen", "/benachrichtigungen", "/portale", "/jobs",
    "/favoriten", "/feintuning", "/lernen", "/scan", "/profil", "/roadmap",
    "/", "/forgot-password", "/verify-pending",
]

# Token-/Redirect-Routen: erwartete Statusmenge, nicht-200 ist KEIN Bug.
EXPECTED_STATUS = {
    # Owner-only per require_owner-Guard (jobscanner/web/app.py) — 403 für Member ist Design.
    "/metriken": {403},
    "/reset-password": {400},
    "/verify-email": {404},
    "/account/email/confirm": {400},
    "/logout": {302, 303},
    "/wizard/new": {302, 303},
    "/login": {200, 302, 303},
    "/register": {200, 302, 303},
}


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


def assert_no_server_error(resp, route):
    assert resp.status_code != 500, f"{route} → 500"
    body = resp.text
    for marker in ERROR_MARKERS:
        assert marker not in body, f"{route} → Fehler-Marker {marker!r} im Body"


@pytest.mark.parametrize("route", CONTENT_ROUTES)
def test_content_route_renders_200_without_error_markers(member_client, route):
    resp = member_client.get(route)
    assert_no_server_error(resp, route)
    assert resp.status_code == 200, f"{route} → {resp.status_code} (erwartet 200)"


@pytest.mark.parametrize("route", sorted(EXPECTED_STATUS))
def test_token_and_redirect_routes_have_expected_status(member_client, route):
    resp = member_client.get(route, follow_redirects=False)
    assert_no_server_error(resp, route)
    assert resp.status_code in EXPECTED_STATUS[route], \
        f"{route} → {resp.status_code} (erwartet {EXPECTED_STATUS[route]})"
