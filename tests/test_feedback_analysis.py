"""Tests für Feedback-Analyse: feedback_analysis/insights-CRUD, Insight-Wirkung,
Rescore-Enqueue, feedback_agent-CLI."""
import json

import pytest

from jobscanner import storage
from jobscanner.models import Job


@pytest.fixture(autouse=True)
def db(tmp_path):
    storage.init_db(tmp_path / "jobs.db")
    yield
    storage.close()


def _default_profile():
    pid = storage.create_profile("Tjark", {}, is_default=True)
    storage.save_criteria(pid, [
        {"key": "location", "label": "Standort", "weight": 3, "sort": 0},
        {"key": "remote", "label": "Remote", "weight": 4, "sort": 1},
    ])
    return pid


def test_create_analysis_starts_in_analyzing():
    pid = _default_profile()
    aid = storage.create_analysis(pid)
    a = storage.get_analysis(aid)
    assert a["profile_id"] == pid
    assert a["status"] == "analyzing"
    assert a["cards"] == {}
    assert a["answers"] == {}


def test_save_cards_sets_pending_review_via_status_call():
    pid = _default_profile()
    aid = storage.create_analysis(pid)
    cards = {"up_muster": ["Remote + kleine Studios"], "down_muster": ["Senior onsite"],
             "widersprüche": [{"jobA": "A", "jobB": "B", "frage": "warum?"}]}
    storage.save_analysis_cards(aid, cards)
    storage.set_analysis_status(aid, "pending_review")
    a = storage.get_analysis(aid)
    assert a["cards"] == cards
    assert a["status"] == "pending_review"


def test_save_answers_roundtrip():
    pid = _default_profile()
    aid = storage.create_analysis(pid)
    answers = {"up_muster": [True, False], "widersprüche": ["B war München"]}
    storage.save_analysis_answers(aid, answers)
    assert storage.get_analysis(aid)["answers"] == answers


def test_get_latest_analysis_returns_newest():
    pid = _default_profile()
    storage.create_analysis(pid)
    aid2 = storage.create_analysis(pid)
    assert storage.get_latest_analysis(pid)["id"] == aid2


def test_get_latest_analysis_none_when_empty():
    pid = _default_profile()
    assert storage.get_latest_analysis(pid) is None


def test_add_and_list_insights_filters_by_status():
    pid = _default_profile()
    storage.add_insight(pid, "preference", "Bevorzugt Remote + kleine Studios")
    storage.add_insight(pid, "weight", "", payload={"key": "location", "old_weight": 3, "new_weight": 5})
    proposed = storage.list_insights(pid, status="proposed")
    assert len(proposed) == 2
    assert proposed[0]["status"] == "proposed"
    assert storage.list_insights(pid, status="confirmed") == []


def test_confirm_preference_appends_to_profile_preferences():
    pid = _default_profile()
    iid = storage.add_insight(pid, "preference", "Hamburg stark, aber Gesamtpassung entscheidet")
    storage.confirm_insight(iid)
    assert storage.list_insights(pid, status="confirmed")[0]["id"] == iid
    prefs = storage.get_profile(pid)["data"].get("preferences", [])
    assert prefs == ["Hamburg stark, aber Gesamtpassung entscheidet"]


def test_confirm_weight_patches_criterion_weight():
    pid = _default_profile()
    iid = storage.add_insight(pid, "weight", "",
                              payload={"key": "location", "old_weight": 3, "new_weight": 5})
    storage.confirm_insight(iid)
    weights = {c["key"]: c["weight"] for c in storage.list_criteria(pid)}
    assert weights["location"] == 5
    assert weights["remote"] == 4  # unangetastet


def test_reject_insight_sets_rejected_and_no_side_effect():
    pid = _default_profile()
    iid = storage.add_insight(pid, "preference", "irrelevant")
    storage.reject_insight(iid)
    assert storage.list_insights(pid, status="rejected")[0]["id"] == iid
    assert storage.get_profile(pid)["data"].get("preferences", []) == []
