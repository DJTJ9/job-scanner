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
