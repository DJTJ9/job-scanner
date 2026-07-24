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
