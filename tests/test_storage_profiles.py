"""Tests für Profile-, Kriterien-, Feedback- und Job-Score-Storage."""
import sqlite3

import pytest

from jobscanner import storage


@pytest.fixture(autouse=True)
def db(tmp_path):
    storage.init_db(tmp_path / "jobs.db")
    yield
    storage.close()


def _mk_profile(**overrides):
    args = dict(name="Testi", data={"level": "junior", "skills": ["Unity"],
                                    "no_gos": ["Zeitarbeit"]},
                queries={"unity_games": {"de": ["unity entwickler"]}})
    args.update(overrides)
    return storage.create_profile(**args)


def test_create_and_get_profile_roundtrip():
    pid = _mk_profile()
    p = storage.get_profile(pid)
    assert p["name"] == "Testi"
    assert p["data"]["skills"] == ["Unity"]
    assert p["queries"] == {"unity_games": {"de": ["unity entwickler"]}}
    assert p["active"] is True
    assert p["is_default"] is False


def test_get_profile_by_name_and_missing():
    _mk_profile()
    assert storage.get_profile_by_name("Testi")["name"] == "Testi"
    assert storage.get_profile_by_name("gibtsnicht") is None


def test_duplicate_profile_name_raises():
    _mk_profile()
    with pytest.raises(sqlite3.IntegrityError):
        _mk_profile()


def test_list_profiles_active_filter():
    _mk_profile()
    pid2 = _mk_profile(name="Inaktiv")
    conn = storage._require_conn()
    conn.execute("UPDATE profiles SET active = 0 WHERE id = ?", (pid2,))
    conn.commit()
    assert {p["name"] for p in storage.list_profiles()} == {"Testi", "Inaktiv"}
    assert {p["name"] for p in storage.list_profiles(active_only=True)} == {"Testi"}


def test_save_and_list_criteria_sorted():
    pid = _mk_profile()
    storage.save_criteria(pid, [
        {"key": "tech_stack", "label": "Tech-Stack", "weight": 4, "sort": 1},
        {"key": "role_fit", "label": "Zielrollen-Passung", "weight": 5, "sort": 0},
    ])
    crits = storage.list_criteria(pid)
    assert [c["key"] for c in crits] == ["role_fit", "tech_stack"]
    assert crits[0]["weight"] == 5


def test_save_criteria_replaces_existing():
    pid = _mk_profile()
    storage.save_criteria(pid, [{"key": "a", "label": "A", "weight": 1, "sort": 0}])
    storage.save_criteria(pid, [{"key": "b", "label": "B", "weight": 2, "sort": 0}])
    assert [c["key"] for c in storage.list_criteria(pid)] == ["b"]


def test_set_criterion_weight():
    pid = _mk_profile()
    storage.save_criteria(pid, [{"key": "a", "label": "A", "weight": 1, "sort": 0}])
    cid = storage.list_criteria(pid)[0]["id"]
    storage.set_criterion_weight(cid, 5)
    assert storage.list_criteria(pid)[0]["weight"] == 5


def test_weight_out_of_range_raises():
    pid = _mk_profile()
    with pytest.raises(sqlite3.IntegrityError):
        storage.save_criteria(pid, [{"key": "a", "label": "A", "weight": 6, "sort": 0}])


def test_feedback_upsert_and_list():
    pid = _mk_profile()
    storage.add_feedback(pid, "fp1", "up")
    storage.add_feedback(pid, "fp1", "down")   # zweiter Vote überschreibt
    fb = storage.list_feedback(pid)
    assert len(fb) == 1
    assert fb[0]["vote"] == "down"


def test_feedback_invalid_vote_raises():
    pid = _mk_profile()
    with pytest.raises(sqlite3.IntegrityError):
        storage.add_feedback(pid, "fp1", "maybe")


def test_job_score_upsert_and_get():
    pid = _mk_profile()
    storage.upsert_job_score(pid, "fp1", 87, "passt gut", "Pass",
                             {"role_fit": {"punkte": 9, "grund": "Unity-Rolle"}})
    s = storage.get_job_score(pid, "fp1")
    assert s["score"] == 87
    assert s["breakdown"]["role_fit"]["punkte"] == 9
    storage.upsert_job_score(pid, "fp1", 42, "neu bewertet", "Vielleicht", {})
    assert storage.get_job_score(pid, "fp1")["score"] == 42
    assert storage.get_job_score(pid, "fp2") is None


def test_migrate_yaml_profile_creates_tjark_with_seed_criteria():
    pid = storage.migrate_yaml_profile()
    p = storage.get_profile(pid)
    assert p["name"] == "Tjark"
    assert p["is_default"] is True
    assert "Unity" in p["data"]["skills"]
    assert p["queries"]  # queries.yaml übernommen
    crits = storage.list_criteria(pid)
    assert {c["key"] for c in crits} == {c["key"] for c in storage.DEFAULT_CRITERIA}
    assert all(0 <= c["weight"] <= 5 for c in crits)


def test_migrate_yaml_profile_is_idempotent():
    pid1 = storage.migrate_yaml_profile()
    storage.set_criterion_weight(storage.list_criteria(pid1)[0]["id"], 0)
    pid2 = storage.migrate_yaml_profile()
    assert pid1 == pid2
    assert len(storage.list_profiles()) == 1
    # zweiter Lauf überschreibt manuell geänderte Gewichte NICHT
    assert storage.list_criteria(pid1)[0]["weight"] == 0


def test_delete_profile_removes_profile_and_dependents():
    pid = storage.create_profile("Weg", {"skills": ["python"]})
    storage.save_criteria(pid, [{"key": "skills", "label": "Skills", "weight": 3, "sort": 0}])
    storage.add_feedback(pid, "fp1", "up")
    storage.delete_profile(pid)
    assert storage.get_profile(pid) is None
    assert storage.list_criteria(pid) == []
    assert storage.list_feedback(pid) == []


def test_delete_profile_leaves_other_profiles():
    keep = storage.create_profile("Bleibt", {})
    drop = storage.create_profile("Weg", {})
    storage.delete_profile(drop)
    assert storage.get_profile(keep) is not None
    assert storage.get_profile(drop) is None


def test_update_profile_overwrites_name_and_data():
    pid = storage.create_profile("Alt", {"skills": ["python"]})
    storage.update_profile(pid, "Neu", {"skills": ["rust"], "level": "senior"})
    p = storage.get_profile(pid)
    assert p["name"] == "Neu"
    assert p["data"] == {"skills": ["rust"], "level": "senior"}


def test_update_profile_with_queries_overwrites_queries_json():
    pid = storage.create_profile("Alt", {"skills": ["python"]},
                                 queries={"old_role": {"alle": ["Old Term"]}})
    storage.update_profile(pid, "Neu", {"skills": ["rust"]},
                           queries={"new_role": {"alle": ["New Term"]}})
    p = storage.get_profile(pid)
    assert p["queries"] == {"new_role": {"alle": ["New Term"]}}


def test_update_profile_with_empty_queries_clears_queries_json():
    pid = storage.create_profile("Alt", {}, queries={"role": {"alle": ["Term"]}})
    storage.update_profile(pid, "Alt", {}, queries={})
    p = storage.get_profile(pid)
    assert p["queries"] is None


def test_update_profile_without_queries_arg_preserves_existing_queries_json():
    pid = storage.create_profile("Alt", {}, queries={"role": {"alle": ["Term"]}})
    storage.update_profile(pid, "Neu", {"skills": ["rust"]})
    p = storage.get_profile(pid)
    assert p["queries"] == {"role": {"alle": ["Term"]}}
