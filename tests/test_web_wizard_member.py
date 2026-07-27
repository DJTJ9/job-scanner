"""Member-Wizard: Katalog-No-Gos + -Weights, sofortiges deterministisches Scoring."""
import pytest
from fastapi.testclient import TestClient
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
    # Geteilten Pool füllen (extraction_status default 'extracted')
    storage.upsert_job(Job(title="Junior Unity Developer", company="A GmbH", location="Hamburg",
                           remote_flag="remote", language="de", tech_stack=["Unity"]))
    storage.upsert_job(Job(title="Senior Architect", company="B GmbH", location="Berlin",
                           remote_flag="onsite", language="de", requirements=["5 Jahre"]))
    uid = storage.create_user("member@test.de", "pw", role="member")
    storage.mark_email_verified(uid)
    c = CSRFTestClient(app)
    c.post("/login", data={"email": "member@test.de", "password": "pw"})
    return c


def _run_wizard(client, no_gos, weights):
    client.get("/wizard/new")
    client.post("/wizard/basis", data={"name": "MemberProfil", "level": "junior",
                                       "experience_years": "0"})
    client.post("/wizard/skills", data={"skills": "Unity"})
    client.post("/wizard/zielrollen", data={"target_roles": "Unity Developer"})
    client.post("/wizard/ort_umfang", data={"location": "Hamburg", "employment": "Vollzeit",
                                            "languages": "de"})
    client.post("/wizard/no_gos", data={"no_gos": no_gos})   # Liste → Mehrfach-Checkbox
    return client.post("/wizard/gewichte", data=weights, follow_redirects=False)


def test_no_gos_step_renders_catalog_for_member(client):
    client.get("/wizard/new")
    resp = client.get("/wizard/no_gos")
    assert 'name="no_gos" value="senior_5j"' in resp.text
    assert "Zeitarbeit" in resp.text


def test_gewichte_step_renders_full_catalog_for_member(client):
    resp = client.get("/wizard/gewichte")
    assert 'name="weight_junior_level"' in resp.text
    assert 'name="weight_domaene"' in resp.text


def test_member_wizard_stores_catalog_keys_and_scores_immediately(client):
    resp = _run_wizard(
        client, no_gos=["senior_5j", "nur_onsite"],
        weights={"weight_remote": "5", "weight_junior_level": "5"})
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    pid = storage.get_profile_by_name("MemberProfil")["id"]

    profile = storage.get_profile(pid)
    assert profile["data"]["no_gos"] == ["senior_5j", "nur_onsite"]
    crits = {c["key"] for c in storage.list_criteria(pid)}
    assert "remote" in crits and "junior_level" in crits and len(crits) >= 25

    # Sofort bewertet — ohne LLM: beide Pool-Jobs haben einen Score
    scored = storage.list_jobs_with_scores(pid)
    by_title = {e["job"].title: e for e in scored}
    assert by_title["Junior Unity Developer"]["score"] is not None
    assert by_title["Senior Architect"]["category"] == "No-Go"   # senior_5j Veto


def test_member_criteria_save_rescore_deterministic(client):
    resp = _run_wizard(client, no_gos=[], weights={"weight_remote": "5"})
    assert resp.headers["location"] == "/"
    pid = storage.get_profile_by_name("MemberProfil")["id"]
    # Feintuning: junior_level hochziehen → weiterhin bewertet, ohne LLM
    client.post(f"/dashboard/{pid}/criteria",
                data={"weight_remote": "5", "weight_junior_level": "5"})
    scored = storage.list_jobs_with_scores(pid)
    assert any(e["score"] is not None for e in scored)
