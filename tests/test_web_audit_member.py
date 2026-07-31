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


# --- Task 2: dynamische Routen (geseedetes Member-Profil) + Broken-Link-Scan ---
from jobscanner.models import Job

# Reale Wizard-Schrittfolge (jobscanner/web/app.py: STEP_ORDER) — der Plan-Entwurf
# hatte "suchbegriffe"/"domaenen" ausgelassen.
WIZARD_STEPS = ["basis", "skills", "zielrollen", "suchbegriffe", "domaenen",
                "ort_umfang", "no_gos", "gewichte"]

# Interne Links, die absichtlich Query/Token brauchen und ohne diesen 4xx liefern —
# vom Broken-Link-Scan ausgenommen (kein Bug).
LINK_SCAN_SKIP_PREFIXES = ("/verify-email", "/reset-password", "/account/email/confirm", "/logout")

# Minimal-realistische Profildaten (Struktur wie vom Wizard persistiert).
_PROFILE_DATA = {
    "level": "junior", "experience_years": 0,
    "skills": ["Unity"], "target_roles": ["Unity Developer"],
    "domains": [], "cities": ["Hamburg"], "employment_types": ["Vollzeit"],
    "languages": ["de"], "no_gos": [], "experience_sources": [], "portfolio": [],
}


def _seed_member_profile(member_client):
    """Legt direkt über den Storage ein Member-Profil (dem Fixture-User gehörend)
    plus einen gescorten Job an und gibt die profile_id zurück — LLM-frei,
    deterministisch. Nutzt den real vorhandenen Seeder storage.create_profile;
    ein create_profile_min existiert nicht."""
    uid = storage.get_user_by_email("member@test.de")["id"]
    pid = storage.create_profile("AuditProfil", dict(_PROFILE_DATA), user_id=uid)
    fp = storage.upsert_job(Job(title="Unity Dev", company="ACME", location="Hamburg",
                                first_seen="2026-07-11"))
    storage.upsert_job_score(pid, fp, 78, "passt gut", "Pass",
                             {"role_fit": {"punkte": 8, "grund": "starke Passung"}})
    return pid


# /dashboard/<pid>            → 301 auf /jobs (Legacy-Bookmark-Redirect) → 200 nach Follow.
# /dashboard/<pid>/metriken   → 301 auf /metriken (owner-only, 403 für Member) — Design.
# /dashboard/<pid>/analysis   → require_owner → 403 für Member — Design (owner-only).
@pytest.mark.parametrize("suffix", [
    "",
    pytest.param("/metriken", marks=pytest.mark.xfail(
        reason="owner-only: 301→/metriken→403 für Member (Design, analog Task-1-/metriken)",
        strict=True)),
    pytest.param("/analysis", marks=pytest.mark.xfail(
        reason="owner-only: require_owner→403 für Member (Design)", strict=True)),
])
def test_dashboard_dynamic_routes_no_server_error(member_client, suffix):
    pid = _seed_member_profile(member_client)
    route = f"/dashboard/{pid}{suffix}"
    resp = member_client.get(route)
    assert_no_server_error(resp, route)
    assert resp.status_code == 200, f"{route} → {resp.status_code}"


def test_wizard_edit_dynamic_route_no_server_error(member_client):
    pid = _seed_member_profile(member_client)
    route = f"/wizard/edit/{pid}"
    resp = member_client.get(route, follow_redirects=True)
    assert_no_server_error(resp, route)
    assert resp.status_code == 200, f"{route} → {resp.status_code}"


@pytest.mark.parametrize("step", WIZARD_STEPS)
def test_wizard_steps_no_server_error(member_client, step):
    member_client.get("/wizard/new")
    route = f"/wizard/{step}"
    resp = member_client.get(route)
    assert_no_server_error(resp, route)
    assert resp.status_code == 200, f"{route} → {resp.status_code}"


def test_no_broken_internal_links_on_content_pages(member_client):
    """Sammelt alle href="/..."-Links der gerenderten Content-Seiten und prüft,
    dass keiner 500 liefert und keiner 404 ist (außer bewusst token-gated)."""
    href_re = re.compile(r'href="(/[^"#?]*)"')
    seen = set()
    for route in CONTENT_ROUTES:
        html = member_client.get(route).text
        for link in href_re.findall(html):
            if link.startswith("/admin"):
                continue
            if any(link.startswith(p) for p in LINK_SCAN_SKIP_PREFIXES):
                continue
            seen.add(link)
    broken = []
    for link in sorted(seen):
        r = member_client.get(link, follow_redirects=False)
        if r.status_code >= 500 or r.status_code == 404:
            broken.append(f"{link} → {r.status_code}")
    assert not broken, "Kaputte interne Links: " + ", ".join(broken)
