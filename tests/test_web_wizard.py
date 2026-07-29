"""Tests für den 6-Schritte-Profil-Wizard inkl. optionaler LLM-Verfeinerung (gemockt)."""
import pytest
from fastapi.testclient import TestClient
from _csrf_client import CSRFTestClient

from jobscanner import storage
from jobscanner.web import llm_refine
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
    resp = client.post("/wizard/gewichte", data={"weight_remote": "5"}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"

    profile = storage.get_profile_by_name("Testprofil")
    assert profile is not None
    assert profile["data"]["skills"] == ["Python", "Unity"]
    assert profile["data"]["target_roles"] == ["Backend Developer"]
    assert profile["data"]["no_gos"] == ["Zeitarbeit"]
    assert profile["queries"] is None
    # B3: Owner-Wizard seedet jetzt die 25 WEIGHTS_CATALOG-Kriterien (kein role_fit mehr)
    crits = storage.list_criteria(profile["id"])
    assert len(crits) == 25
    remote = next(c for c in crits if c["key"] == "remote")
    assert remote["weight"] == 5


def test_wizard_suchbegriffe_step_stores_queries_json(client):
    client.get("/wizard/new")
    client.post("/wizard/basis", data={"name": "QueryProfil", "level": "junior",
                                       "experience_years": "1"})
    client.post("/wizard/skills", data={"skills": "Python"})
    client.post("/wizard/zielrollen", data={"target_roles": "Unity Developer"})
    client.post("/wizard/suchbegriffe", data={"terms_0": ["Unity Developer", "Gameplay Engineer"]})
    client.post("/wizard/domaenen", data={"domains": []})
    client.post("/wizard/ort_umfang", data={"cities": "Berlin", "languages": ["de"]})
    client.post("/wizard/no_gos", data={"no_gos": ""})
    resp = client.post("/wizard/gewichte", data={}, follow_redirects=False)
    assert resp.status_code == 303
    profiles = storage.list_profiles()
    p = next(p for p in profiles if p["name"] == "QueryProfil")
    assert p["queries"] == {"Unity Developer": {"alle": ["Unity Developer", "Gameplay Engineer"]}}


def test_wizard_suchbegriffe_step_no_custom_queries_stores_none(client):
    client.get("/wizard/new")
    client.post("/wizard/basis", data={"name": "NoQueryProfil", "level": "junior",
                                       "experience_years": "1"})
    client.post("/wizard/skills", data={"skills": "Python"})
    client.post("/wizard/zielrollen", data={"target_roles": "Backend Dev"})
    client.post("/wizard/suchbegriffe", data={"no_custom_queries": "1"})
    client.post("/wizard/domaenen", data={"domains": []})
    client.post("/wizard/ort_umfang", data={"cities": "Berlin", "languages": ["de"]})
    client.post("/wizard/no_gos", data={"no_gos": ""})
    client.post("/wizard/gewichte", data={}, follow_redirects=False)
    profiles = storage.list_profiles()
    p = next(p for p in profiles if p["name"] == "NoQueryProfil")
    assert p["queries"] is None


def test_wizard_zielrollen_step_links_to_suchbegriffe_next(client):
    client.get("/wizard/new")
    client.post("/wizard/basis", data={"name": "OrderCheck", "level": "junior",
                                       "experience_years": "1"})
    client.post("/wizard/skills", data={"skills": "Python"})
    resp = client.post("/wizard/zielrollen", data={"target_roles": "Dev"},
                       follow_redirects=False)
    assert resp.headers["location"] == "/wizard/suchbegriffe"


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


def test_wizard_owner_no_gos_merges_suggested(client):
    client.get("/wizard/new")
    client.post("/wizard/basis", data={"name": "NoGoOwner", "level": "senior",
                                       "experience_years": "3"})
    client.post("/wizard/skills", data={"skills": "Python"})
    client.post("/wizard/zielrollen", data={"target_roles": "Dev"})
    client.post("/wizard/domaenen", data={"domains": []})
    client.post("/wizard/ort_umfang", data={"cities": "Berlin", "languages": ["de"]})
    client.post("/wizard/no_gos", data={"no_gos": "Zeitarbeit", "suggested_no_gos": ["Nachtschicht"]})
    resp = client.post("/wizard/gewichte", data={}, follow_redirects=False)
    assert resp.status_code in (200, 303)

    profile = storage.get_profile_by_name("NoGoOwner")
    assert set(profile["data"]["no_gos"]) == {"Zeitarbeit", "Nachtschicht"}


def test_wizard_step_invalid_redirects_to_new(client):
    resp = client.get("/wizard/nonexistent", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/wizard/new"


def test_wizard_domaenen_and_ort_presets_stored(client):
    client.get("/wizard/new")
    client.post("/wizard/basis", data={"name": "PresetProfil", "level": "junior",
                                       "experience_years": "0"})
    client.post("/wizard/skills", data={"skills": "Python", "suggested_skills": ["Unity", "C#"]})
    client.post("/wizard/zielrollen", data={"target_roles": "", "suggested_roles": ["Gameplay Programmer"]})
    client.post("/wizard/domaenen", data={"domains": ["games", "sport", "bogus"]})
    client.post("/wizard/ort_umfang", data={
        "cities": "Hannover", "suggested_cities": ["Hamburg", "Berlin"],
        "employment_types": ["Vollzeit", "Werkstudent"],
        "languages": ["de", "en"], "languages_free": "Dänisch"})
    client.post("/wizard/no_gos", data={"no_gos": ""})
    resp = client.post("/wizard/gewichte", data={}, follow_redirects=False)
    assert resp.status_code == 303

    d = storage.get_profile_by_name("PresetProfil")["data"]
    assert d["domains"] == ["games", "sport"]                 # "bogus" gefiltert
    assert set(d["cities"]) == {"Hannover", "Hamburg", "Berlin"}
    assert d["employment_types"] == ["Vollzeit", "Werkstudent"]
    assert set(d["languages"]) == {"de", "en", "Dänisch"}
    assert set(d["skills"]) == {"Python", "Unity", "C#"}
    assert d["target_roles"] == ["Gameplay Programmer"]


def test_wizard_renders_labels_and_suggestion_chips(client):
    client.get("/wizard/new")
    basis = client.get("/wizard/basis").text
    assert "Basics" in basis and "Domänen" in basis and "Ort und Umfang" in basis and "No-Gos" in basis
    assert "0m" not in basis and "5m" not in basis   # Zeitangaben entfernt
    assert 'name="suggested_skills" value="Unity"' in client.get("/wizard/skills").text
    assert 'name="suggested_roles" value="Gameplay Programmer"' in client.get("/wizard/zielrollen").text
    dom = client.get("/wizard/domaenen").text
    assert 'name="domains" value="games"' in dom and 'name="domains" value="sport"' in dom
    ort = client.get("/wizard/ort_umfang").text
    assert 'name="suggested_cities" value="Hamburg"' in ort
    assert 'name="employment_types" value="Vollzeit"' in ort
    assert 'name="languages" value="de"' in ort and "Deutsch" in ort
    assert ort.count("checked") >= 2   # de + en vorausgewählt


def test_wizard_requires_login(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "x")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "y")
    app = create_app(db_path=tmp_path / "jobs.db")
    anon = CSRFTestClient(app)
    resp = anon.get("/wizard/new", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def _make_owner_profile(client):
    """Legt über den vollen Wizard-Flow ein Profil an (owner-Fixture) und gibt seine id zurück."""
    client.get("/wizard/new")
    client.post("/wizard/basis", data={"name": "SprungProfil", "level": "mid",
                                       "experience_years": "3"})
    client.post("/wizard/skills", data={"skills": "Python"})
    client.post("/wizard/zielrollen", data={"target_roles": "Backend Developer"})
    client.post("/wizard/suchbegriffe", data={"no_custom_queries": "1"})
    client.post("/wizard/domaenen", data={"domains": []})
    client.post("/wizard/ort_umfang", data={"cities": "Berlin", "languages": ["de"]})
    client.post("/wizard/no_gos", data={"no_gos": ""})
    client.post("/wizard/gewichte", data={"weight_role_fit": "5"})
    return storage.get_profile_by_name("SprungProfil")["id"]


def test_wizard_edit_jump_to_any_step(client):
    pid = _make_owner_profile(client)
    client.get(f"/wizard/edit/{pid}")
    resp = client.post("/wizard/basis",
                       data={"name": "SprungProfil", "level": "mid", "experience_years": "3",
                             "goto": "no_gos"},
                       follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/wizard/no_gos"


def test_wizard_new_setup_blocks_unvisited_jump(client):
    client.get("/wizard/new")  # folgt Redirect → GET /wizard/basis (visited=[basis])
    resp = client.post("/wizard/basis",
                       data={"name": "X", "level": "junior", "experience_years": "0",
                             "goto": "no_gos"},
                       follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/wizard/skills"  # Fallback: sequenzieller Next


def test_wizard_new_setup_allows_visited_backjump(client):
    client.get("/wizard/new")
    client.post("/wizard/basis", data={"name": "X", "level": "junior", "experience_years": "0"})
    client.post("/wizard/skills", data={"skills": "Python"})  # visited akkumuliert über Redirect-GETs
    resp = client.post("/wizard/zielrollen",
                       data={"target_roles": "Dev", "goto": "basis"},
                       follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/wizard/basis"


def test_wizard_goto_saves_current_step(client):
    pid = _make_owner_profile(client)
    client.get(f"/wizard/edit/{pid}")
    client.post("/wizard/basis",
                data={"name": "Geaendert", "level": "senior", "experience_years": "9",
                      "goto": "no_gos"})
    form = client.get("/wizard/basis")
    assert 'value="Geaendert"' in form.text  # basis-Daten im Sprung gespeichert


def test_wizard_invalid_goto_falls_back_to_next(client):
    client.get("/wizard/new")
    resp = client.post("/wizard/basis",
                       data={"name": "X", "level": "junior", "experience_years": "0",
                             "goto": "kein_step"},
                       follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/wizard/skills"


def test_wizard_jump_from_gewichte_does_not_submit(client):
    pid = _make_owner_profile(client)
    before = storage.get_profile(pid)["name"]
    client.get(f"/wizard/edit/{pid}")
    resp = client.post("/wizard/gewichte",
                       data={"weight_role_fit": "0", "goto": "basis"},
                       follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/wizard/basis"  # Sprung statt Create/Update
    assert storage.get_profile(pid)["name"] == before   # kein vorzeitiges Update


def test_progressbar_edit_renders_goto_buttons(client):
    pid = _make_owner_profile(client)
    client.get(f"/wizard/edit/{pid}")
    page = client.get("/wizard/basis")
    assert 'name="goto" value="no_gos"' in page.text      # Edit: entfernter Step springbar
    assert 'name="goto" value="basis"' not in page.text   # aktueller Step ist kein Sprung-Button


def test_progressbar_new_setup_unvisited_is_not_jumpable(client):
    client.get("/wizard/new")
    page = client.get("/wizard/basis")
    assert 'name="goto" value="no_gos"' not in page.text   # unbesuchter Step nicht springbar
