"""Tests für den 6-Schritte-Profil-Wizard inkl. optionaler LLM-Verfeinerung (gemockt)."""
import pytest
from fastapi.testclient import TestClient

from jobscanner import storage
from jobscanner.web import llm_refine
from jobscanner.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "geheim123")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@test.de")
    app = create_app(db_path=tmp_path / "jobs.db")
    c = TestClient(app)
    c.post("/login", data={"email": "owner@test.de", "password": "geheim123"})
    return c


def test_wizard_new_redirects_to_first_step(client):
    resp = client.get("/wizard/new", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/wizard/basis"


def test_wizard_full_flow_creates_profile(client):
    client.get("/wizard/new")
    client.post("/wizard/basis", data={"name": "Testprofil", "level": "junior",
                                       "experience_years": "1"})
    client.post("/wizard/skills", data={"skills": "Python, Unity"})
    client.post("/wizard/zielrollen", data={"target_roles": "Backend Developer"})
    client.post("/wizard/ort_umfang", data={"location": "Remote", "employment": "Vollzeit",
                                            "languages": "de, en"})
    client.post("/wizard/no_gos", data={"no_gos": "Zeitarbeit"})
    resp = client.post("/wizard/gewichte", data={"weight_role_fit": "5"}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/dashboard/")

    profile = storage.get_profile_by_name("Testprofil")
    assert profile is not None
    assert profile["data"]["skills"] == ["Python", "Unity"]
    assert profile["data"]["target_roles"] == ["Backend Developer"]
    assert profile["data"]["no_gos"] == ["Zeitarbeit"]
    assert profile["queries"] is None
    crits = storage.list_criteria(profile["id"])
    role_fit = next(c for c in crits if c["key"] == "role_fit")
    assert role_fit["weight"] == 5


def test_wizard_llm_refine_merges_suggested_skills(client, monkeypatch):
    monkeypatch.setattr(
        llm_refine, "suggest_from_freetext",
        lambda text: {"skills": ["Groq", "FastAPI"], "target_roles": [], "criteria_weights": {}})
    client.get("/wizard/new")
    client.post("/wizard/basis", data={"name": "Testprofil2", "level": "mid",
                                       "experience_years": "3"})
    resp = client.post("/wizard/llm-refine", data={"freetext": "5 Jahre Python, Groq-APIs"},
                       follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/wizard/skills"

    skills_page = client.get("/wizard/skills")
    assert "Groq" in skills_page.text  # Vorschlag als Checkbox gerendert

    client.post("/wizard/skills", data={"skills": "Python", "suggested_skills": "Groq"})
    client.post("/wizard/zielrollen", data={"target_roles": "Backend"})
    client.post("/wizard/ort_umfang", data={"location": "Remote", "employment": "Vollzeit",
                                            "languages": "de"})
    client.post("/wizard/no_gos", data={"no_gos": ""})
    client.post("/wizard/gewichte", data={})

    profile = storage.get_profile_by_name("Testprofil2")
    assert set(profile["data"]["skills"]) == {"Python", "Groq"}


def test_wizard_step_invalid_redirects_to_new(client):
    resp = client.get("/wizard/nonexistent", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/wizard/new"


def test_wizard_requires_login(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "x")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "y")
    app = create_app(db_path=tmp_path / "jobs.db")
    anon = TestClient(app)
    resp = anon.get("/wizard/new", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"
