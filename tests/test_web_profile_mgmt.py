"""P5: Profil bearbeiten/löschen über Web-UI."""
import pytest
from fastapi.testclient import TestClient
from _csrf_client import CSRFTestClient

from jobscanner import storage
from jobscanner.web.app import create_app


@pytest.fixture
def member(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "geheim123")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@test.de")
    app = create_app(db_path=tmp_path / "jobs.db")
    uid = storage.create_user("m@test.de", "pw", role="member")
    storage.mark_email_verified(uid)
    c = CSRFTestClient(app)
    c.post("/login", data={"email": "m@test.de", "password": "pw"})
    return c, uid


def _make_profile(uid):
    pid = storage.create_profile("MeinProfil", {"skills": ["python"], "level": "mid"},
                                 user_id=uid)
    storage.save_criteria(pid, [{"key": "skills", "label": "Skills", "weight": 4, "sort": 0}])
    return pid


def test_profiles_page_shows_edit_and_delete_buttons(member):
    c, uid = member
    pid = _make_profile(uid)
    resp = c.get("/profil")
    assert f'href="/wizard/edit/{pid}"' in resp.text
    assert f'action="/profiles/{pid}/delete"' in resp.text


def test_delete_route_removes_profile_and_redirects(member):
    c, uid = member
    pid = _make_profile(uid)
    resp = c.post(f"/profiles/{pid}/delete", follow_redirects=False)
    assert resp.status_code == 303
    assert storage.get_profile(pid) is None


def test_delete_foreign_profile_blocked(member):
    c, uid = member
    other = storage.create_user("x@test.de", "pw", role="member")
    pid = storage.create_profile("Fremd", {}, user_id=other)
    resp = c.post(f"/profiles/{pid}/delete", follow_redirects=False)
    assert resp.status_code == 404
    assert storage.get_profile(pid) is not None


def test_edit_route_loads_wizard_and_prefills_name(member):
    c, uid = member
    pid = _make_profile(uid)
    resp = c.get(f"/wizard/edit/{pid}", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/wizard/basis"
    form = c.get("/wizard/basis")
    assert 'value="MeinProfil"' in form.text
    assert 'value="mid"' in form.text


def test_edit_submit_updates_instead_of_creating(member):
    c, uid = member
    pid = _make_profile(uid)
    before = len(storage.list_profiles(user_id=uid))
    c.get(f"/wizard/edit/{pid}")
    # bis zum letzten Schritt durchklicken, Name im basis-Schritt ändern
    c.post("/wizard/basis", data={"name": "Umbenannt", "level": "senior", "experience_years": "5"})
    for step in ("skills", "zielrollen", "domaenen", "ort_umfang", "no_gos"):
        c.post(f"/wizard/{step}", data={})
    c.post("/wizard/gewichte", data={"weight_remote": "5"})
    after = storage.list_profiles(user_id=uid)
    assert len(after) == before  # kein neues Profil
    assert storage.get_profile(pid)["name"] == "Umbenannt"
