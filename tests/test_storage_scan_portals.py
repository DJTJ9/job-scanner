"""Tests für die Portal-Auswahl (residential Browser-Scan) in data_json."""
import pytest

from jobscanner import storage


@pytest.fixture(autouse=True)
def db(tmp_path):
    storage.init_db(tmp_path / "jobs.db")
    yield
    storage.close()


def test_default_is_all_portals():
    assert storage.get_scan_portals({}) == ["stepstone", "indeed"]


def test_unknown_portal_names_filtered():
    assert storage.get_scan_portals({"scan_portals": ["indeed", "monster"]}) == ["indeed"]


def test_empty_selection_stays_empty():
    # Leere Liste = bewusstes Opt-out, NICHT auf Default zurückfallen.
    assert storage.get_scan_portals({"scan_portals": []}) == []


def test_set_scan_portals_writes_all_user_profiles():
    uid = storage.create_user("u@test.de", "pw")
    storage.create_profile("A", {}, user_id=uid)
    storage.create_profile("B", {}, user_id=uid)
    assert storage.set_scan_portals(uid, ["stepstone", "quatsch"]) == 2
    for p in storage.list_profiles(user_id=uid):
        assert p["data"]["scan_portals"] == ["stepstone"]


def _active_portal(uid, template="https://jobs.example.com/s?q={query}",
                   pattern=r"jobs\.example\.com/job/", typ="portal"):
    pid = storage.create_custom_portal("https://jobs.example.com", typ, uid,
                                       search_url_template=template,
                                       detail_url_pattern=pattern)
    storage.save_check_result(pid, {"compatible": True})
    storage.activate_custom_portal(pid)
    return pid


def test_active_custom_portal_id_survives_validation():
    uid = storage.create_user("c@test.de", "pw")
    pid = _active_portal(uid)
    data = {"scan_portals": ["stepstone", f"custom:{pid}"]}
    assert storage.get_scan_portals(data) == ["stepstone", f"custom:{pid}"]


def test_inactive_custom_portal_filtered():
    uid = storage.create_user("c@test.de", "pw")
    pid = storage.create_custom_portal("https://x.de", "portal", uid,
                                       search_url_template="https://x.de/s?q={query}",
                                       detail_url_pattern="x")
    # pending_check, nie aktiviert
    assert storage.get_scan_portals({"scan_portals": [f"custom:{pid}"]}) == []


def test_career_page_without_search_template_not_scannable():
    uid = storage.create_user("c@test.de", "pw")
    pid = _active_portal(uid, template=None, pattern=None, typ="career_page")
    assert storage.get_scan_portals({"scan_portals": [f"custom:{pid}"]}) == []
    assert storage.list_scannable_custom_portals() == []


def test_set_scan_portals_persists_custom_ids():
    uid = storage.create_user("c@test.de", "pw")
    storage.create_profile("A", {}, user_id=uid)
    pid = _active_portal(uid)
    storage.set_scan_portals(uid, ["indeed", f"custom:{pid}", "custom:999"])
    p = storage.list_profiles(user_id=uid)[0]
    assert p["data"]["scan_portals"] == ["indeed", f"custom:{pid}"]
