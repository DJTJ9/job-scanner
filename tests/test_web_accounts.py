"""Tests für Registrierung, Login-Isolation und LLM-Rollen-Gate der Kommilitoninnen-Accounts."""
import pytest
from fastapi.testclient import TestClient
from _csrf_client import CSRFTestClient

from jobscanner import storage
from jobscanner.web.app import create_app


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "ownerpw")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@test.de")
    monkeypatch.setenv("JOBSCANNER_INVITE_CODE", "komm2026")
    return create_app(db_path=tmp_path / "jobs.db")


def _register(client, email="stud@uni.de", pw="studpw", code="komm2026"):
    return client.post("/register",
                       data={"email": email, "password": pw, "invite_code": code,
                             "consent": "on"},
                       follow_redirects=False)


def _verify_and_login(client, email, pw):
    """Markiert die Email als verifiziert und loggt neu ein, damit die Session
    (die /register hart auf email_verified=False setzt) den DB-Zustand übernimmt."""
    storage.mark_email_verified(storage.get_user_by_email(email)["id"])
    client.post("/login", data={"email": email, "password": pw})


def _wizard_profile(client, name):
    client.get("/wizard/new")
    client.post("/wizard/basis", data={"name": name, "level": "junior", "experience_years": "1"})
    client.post("/wizard/skills", data={"skills": "Python"})
    client.post("/wizard/zielrollen", data={"target_roles": "Backend"})
    client.post("/wizard/ort_umfang", data={"location": "Remote", "employment": "Vollzeit",
                                            "languages": "de"})
    client.post("/wizard/no_gos", data={"no_gos": ""})
    resp = client.post("/wizard/gewichte", data={}, follow_redirects=False)
    return resp.headers["location"]  # /dashboard/<id>


def test_register_valid_invite_creates_member_and_logs_in(app):
    c = CSRFTestClient(app)
    resp = _register(c)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    user = storage.get_user_by_email("stud@uni.de")
    assert user["role"] == "member"
    _verify_and_login(c, "stud@uni.de", "studpw")
    assert c.get("/", follow_redirects=False).status_code == 200


def test_register_wrong_invite_rejected(app):
    c = CSRFTestClient(app)
    resp = _register(c, code="falsch")
    assert resp.status_code == 403
    assert storage.get_user_by_email("stud@uni.de") is None


def test_register_duplicate_email_rejected(app):
    c = CSRFTestClient(app)
    _register(c)
    resp = CSRFTestClient(app).post(
        "/register", data={"email": "stud@uni.de", "password": "x", "invite_code": "komm2026",
                           "consent": "on"})
    assert resp.status_code == 409


def test_member_profile_isolated_from_other_member(app):
    a = CSRFTestClient(app)
    _register(a, email="a@uni.de", pw="pwa")
    _verify_and_login(a, "a@uni.de", "pwa")
    a_dash = _wizard_profile(a, "A-Profil")
    a_pid = int(a_dash.rsplit("/", 1)[1])

    b = CSRFTestClient(app)
    _register(b, email="b@uni.de", pw="pwb")
    _verify_and_login(b, "b@uni.de", "pwb")
    # B sieht A's Profil nicht in der Liste …
    assert "A-Profil" not in b.get("/").text
    # … und kann es nicht per URL öffnen.
    assert b.get(f"/dashboard/{a_pid}", follow_redirects=False).status_code == 404


def test_member_sees_own_profile_and_ranking(app):
    c = CSRFTestClient(app)
    _register(c)
    _verify_and_login(c, "stud@uni.de", "studpw")
    dash = _wizard_profile(c, "Mein-Profil")
    resp = c.get(dash)
    assert resp.status_code == 200
    assert "Mein-Profil" in resp.text


def test_member_llm_routes_forbidden(app):
    c = CSRFTestClient(app)
    _register(c)
    _verify_and_login(c, "stud@uni.de", "studpw")
    dash = _wizard_profile(c, "Mein-Profil")
    pid = int(dash.rsplit("/", 1)[1])
    assert c.post("/wizard/llm-refine", data={"freetext": "x"},
                  follow_redirects=False).status_code == 403
    assert c.post(f"/dashboard/{pid}/analyze", follow_redirects=False).status_code == 403
    assert c.post(f"/dashboard/{pid}/apply", follow_redirects=False).status_code == 403


def test_owner_llm_route_not_forbidden(app):
    c = CSRFTestClient(app)
    c.post("/login", data={"email": "owner@test.de", "password": "ownerpw"})
    # Owner erhält KEIN 403 (Redirect 303 nach /wizard/skills ist ok).
    assert c.post("/wizard/llm-refine", data={"freetext": ""},
                  follow_redirects=False).status_code != 403


def test_login_page_has_email_field_and_register_link(app):
    c = CSRFTestClient(app)
    page = c.get("/login").text
    assert 'name="email"' in page
    assert "/register" in page


def test_member_dashboard_hides_owner_only_controls(app):
    c = CSRFTestClient(app)
    _register(c)
    dash = _wizard_profile(c, "Mein-Profil")
    dash_text = c.get(dash).text
    assert "/metriken" not in dash_text  # Metriken bleibt owner-exklusiv
    assert "Votes analysieren" not in dash_text  # Owner-Analyse-Maschine bleibt owner-exklusiv
    # Member-Wizard-skills-Seite ohne LLM-Verfeinerungs-Form:
    c.get("/wizard/new")
    c.post("/wizard/basis", data={"name": "X", "level": "j", "experience_years": "0"})
    assert "/wizard/llm-refine" not in c.get("/wizard/skills").text


def test_owner_dashboard_shows_lernen_tab(app):
    c = CSRFTestClient(app)
    c.post("/login", data={"email": "owner@test.de", "password": "ownerpw"})
    pid = storage.get_profile_by_name("Tjark")["id"]
    assert "Lernen" in c.get(f"/dashboard/{pid}").text


def test_impressum_public_without_login(app):
    c = CSRFTestClient(app)
    resp = c.get("/impressum")
    assert resp.status_code == 200
    assert "Angaben gemäß § 5 TMG" in resp.text
    assert "Reeseberg 178" in resp.text


def test_datenschutz_public_without_login(app):
    c = CSRFTestClient(app)
    resp = c.get("/datenschutz")
    assert resp.status_code == 200
    assert "Datenschutz" in resp.text


def _owner_client(app):
    c = CSRFTestClient(app)
    c.post("/login", data={"email": "owner@test.de", "password": "ownerpw"})
    return c


def test_password_page_requires_login(app):
    c = CSRFTestClient(app)
    resp = c.get("/account/passwort", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_password_change_success(app):
    c = _owner_client(app)
    resp = c.post("/account/passwort", data={
        "current_password": "ownerpw", "new_password": "neupw1",
        "new_password_repeat": "neupw1"}, follow_redirects=False)
    assert resp.status_code == 200
    assert "geändert" in resp.text
    assert storage.verify_password("owner@test.de", "neupw1") is not None


def test_password_change_wrong_current(app):
    c = _owner_client(app)
    resp = c.post("/account/passwort", data={
        "current_password": "falsch", "new_password": "neupw1",
        "new_password_repeat": "neupw1"}, follow_redirects=False)
    assert resp.status_code == 400
    assert "falsch" in resp.text
    assert storage.verify_password("owner@test.de", "ownerpw") is not None


def test_password_change_mismatch(app):
    c = _owner_client(app)
    resp = c.post("/account/passwort", data={
        "current_password": "ownerpw", "new_password": "neupw1",
        "new_password_repeat": "anders"}, follow_redirects=False)
    assert resp.status_code == 400
    assert "überein" in resp.text


def test_password_change_too_short(app):
    c = _owner_client(app)
    resp = c.post("/account/passwort", data={
        "current_password": "ownerpw", "new_password": "kurz",
        "new_password_repeat": "kurz"}, follow_redirects=False)
    assert resp.status_code == 400
    assert "mindestens" in resp.text


def test_forgot_password_always_neutral(app):
    c = CSRFTestClient(app)
    resp = c.post("/forgot-password", data={"email": "nobody@nirgends.de"})
    assert resp.status_code == 200
    assert "existiert" in resp.text.lower()


def test_reset_password_full_flow_sets_new_pw(app):
    storage.create_user("resetme@test.de", "altpw1", role="member")
    token = storage.create_reset_token("resetme@test.de")
    c = CSRFTestClient(app)
    assert c.get(f"/reset-password?token={token}").status_code == 200
    resp = c.post("/reset-password", data={
        "token": token, "new_password": "neupw1", "new_password_repeat": "neupw1"})
    assert resp.status_code == 200
    assert storage.verify_password("resetme@test.de", "neupw1") is not None
    assert storage.get_user_by_reset_token(token) is None


def test_reset_password_invalid_token_shows_error(app):
    c = CSRFTestClient(app)
    resp = c.get("/reset-password?token=falsch")
    assert resp.status_code == 400
    assert "ung" in resp.text.lower()


def test_account_email_change_flow(app):
    c = _owner_client(app)  # owner@test.de eingeloggt
    resp = c.post("/account/email", data={"new_email": "neu-owner@test.de"})
    assert resp.status_code == 200
    assert "gesendet" in resp.text.lower()
    uid = storage.get_user_by_email("owner@test.de")["id"]
    token = storage.get_user(uid)["pending_email_token"]
    resp2 = c.get(f"/account/email/confirm?token={token}")
    assert resp2.status_code == 200
    assert storage.get_user_by_email("neu-owner@test.de") is not None


def test_account_export_returns_json_attachment(app):
    c = _owner_client(app)
    resp = c.get("/account/export")
    assert resp.status_code == 200
    assert "attachment" in resp.headers.get("content-disposition", "")
    assert resp.json()["user"]["email"] == "owner@test.de"


def test_account_delete_requires_correct_password(app):
    storage.create_user("delweb@test.de", "geheim1", role="member")
    c = CSRFTestClient(app)
    c.post("/login", data={"email": "delweb@test.de", "password": "geheim1"})
    bad = c.post("/account/loeschen", data={"current_password": "falsch"},
                 follow_redirects=False)
    assert bad.status_code == 400
    assert storage.get_user_by_email("delweb@test.de") is not None
    ok = c.post("/account/loeschen", data={"current_password": "geheim1"},
                follow_redirects=False)
    assert ok.status_code == 303
    assert ok.headers["location"] == "/login"
    assert storage.get_user_by_email("delweb@test.de") is None


def test_account_email_requires_login(app):
    c = CSRFTestClient(app)
    resp = c.get("/account/email", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"
