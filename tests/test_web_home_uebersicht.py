"""Verlagerte Bob-Vorstellung auf der Startseite (UI-Refine D3)."""
import pytest
from _csrf_client import CSRFTestClient

from jobscanner import storage
from jobscanner.web.app import create_app


def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "geheim123")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@test.de")
    return create_app(db_path=tmp_path / "jobs.db")


@pytest.fixture
def member_client(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    uid = storage.create_user("m@test.de", "pw", role="member")
    storage.mark_email_verified(uid)
    c = CSRFTestClient(app)
    c.post("/login", data={"email": "m@test.de", "password": "pw"})
    return c


@pytest.fixture
def owner_client(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    c = CSRFTestClient(app)
    c.post("/login", data={"email": "owner@test.de", "password": "geheim123"})
    return c


def test_home_has_bob_intro_details(member_client):
    text = member_client.get("/").text
    assert 'class="panel bob-intro"' in text or "bob-intro" in text
    for h in ("Wer bin ich?", "Was kann ich?", "Wie ich arbeite"):
        assert h in text


def test_home_intro_has_tech_chips(member_client):
    text = member_client.get("/").text
    for tech in ("Python", "FastAPI", "Jinja2", "SQLite", "Playwright",
                 "Firecrawl", "Claude", "systemd", "NocoDB", "Caddy"):
        assert f'<span class="chip">{tech}</span>' in text


def test_home_intro_mentions_aussortiert(member_client):
    text = member_client.get("/").text
    assert "Aussortiert" in text
    assert "filtere ich automatisch raus" in text


def test_home_intro_open_without_profile(member_client):
    # Member ohne Profil → Details offen
    assert "<details open" in member_client.get("/").text


def test_home_intro_closed_with_profile(owner_client):
    # Owner-Fixture hat ein Seed-Profil → Details zu (kein `open`-Attribut auf bob-intro)
    text = owner_client.get("/").text
    assert "bob-intro" in text
    # kein offenes Panel wenn Profil existiert
    assert "<details open class=\"panel bob-intro\"" not in text
