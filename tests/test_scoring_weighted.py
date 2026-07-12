"""Tests für kriterienbasiertes Scoring — LLM gemockt, Formel deterministisch."""
from unittest.mock import MagicMock

import pytest

import jobscanner.scoring as scoring
from jobscanner.models import Job


def _job(**overrides) -> Job:
    base = dict(title="Unity Developer", company="ACME GmbH", location="Hamburg",
                employment_type="Vollzeit", requirements=["Unity", "C#"],
                tech_stack=["Unity", "C#"])
    base.update(overrides)
    return Job(**base)


_PROFILE = {"level": "junior", "skills": ["Unity", "C#"],
            "target_roles": ["Unity/Games Programmer"], "no_gos": ["Zeitarbeit"]}

_CRITERIA = [
    {"key": "role_fit", "label": "Zielrollen-Passung", "weight": 5},
    {"key": "remote", "label": "Remote", "weight": 3},
    {"key": "salary", "label": "Gehalt", "weight": 2},
]


def test_compute_weighted_score_normalizes_to_100():
    breakdown = {"role_fit": {"punkte": 10, "grund": "x"},
                 "remote": {"punkte": 10, "grund": "x"},
                 "salary": {"punkte": 10, "grund": "x"}}
    assert scoring.compute_weighted_score(breakdown, _CRITERIA) == 100


def test_compute_weighted_score_mixed_values():
    breakdown = {"role_fit": {"punkte": 8, "grund": "x"},
                 "remote": {"punkte": 5, "grund": "x"},
                 "salary": {"punkte": 0, "grund": "x"}}
    # (8*5 + 5*3 + 0*2) / (10*(5+3+2)) * 100 = 55/100*100 = 55
    assert scoring.compute_weighted_score(breakdown, _CRITERIA) == 55


def test_unknown_criterion_drops_from_numerator_and_denominator():
    breakdown = {"role_fit": {"punkte": 8, "grund": "x"},
                 "remote": {"punkte": 5, "grund": "x"},
                 "salary": {"punkte": None, "grund": "keine Angabe"}}
    # (8*5 + 5*3) / (10*(5+3)) * 100 = 55/80*100 = 68.75 → 69
    assert scoring.compute_weighted_score(breakdown, _CRITERIA) == 69


def test_weight_zero_criterion_is_ignored():
    crits = [dict(_CRITERIA[0]), dict(_CRITERIA[1], weight=0)]
    breakdown = {"role_fit": {"punkte": 10, "grund": "x"},
                 "remote": {"punkte": 0, "grund": "x"}}
    assert scoring.compute_weighted_score(breakdown, crits) == 100


def test_all_unknown_returns_none():
    breakdown = {k["key"]: {"punkte": None, "grund": "?"} for k in _CRITERIA}
    assert scoring.compute_weighted_score(breakdown, _CRITERIA) is None


def test_criteria_score_regex_no_go_skips_llm(monkeypatch):
    called = []
    monkeypatch.setattr(scoring, "llm_criteria_eval",
                        lambda job, prof, crits: called.append(1))
    job = _job(employment_type="Zeitarbeit")
    score, reason, category, breakdown = scoring.criteria_score(job, _PROFILE, _CRITERIA)
    assert (score, category) == (0, "No-Go")
    assert "Zeitarbeit" in reason
    assert called == [] and breakdown == {}


def test_criteria_score_llm_veto(monkeypatch):
    monkeypatch.setattr(scoring, "llm_criteria_eval",
                        lambda job, prof, crits, feedback=None: {"veto": "Zeitarbeit", "kriterien": {}})
    score, reason, category, breakdown = scoring.criteria_score(_job(), _PROFILE, _CRITERIA)
    assert (score, category) == (0, "No-Go")
    assert "Zeitarbeit" in reason


def test_criteria_score_happy_path(monkeypatch):
    monkeypatch.setattr(scoring, "llm_criteria_eval", lambda job, prof, crits, feedback=None: {
        "veto": None,
        "kriterien": {"role_fit": {"punkte": 9, "grund": "Unity-Kernrolle"},
                      "remote": {"punkte": 10, "grund": "voll remote"},
                      "salary": {"punkte": None, "grund": "keine Angabe"}}})
    score, reason, category, breakdown = scoring.criteria_score(_job(), _PROFILE, _CRITERIA)
    # (9*5 + 10*3) / (10*8) * 100 = 75/80*100 = 93.75 → 94
    assert score == 94
    assert category == "Pass"
    assert breakdown["role_fit"]["punkte"] == 9
    assert "Unity-Kernrolle" in reason


def test_criteria_score_llm_error_returns_none(monkeypatch):
    def boom(job, prof, crits, feedback=None):
        raise RuntimeError("API down")
    monkeypatch.setattr(scoring, "llm_criteria_eval", boom)
    score, reason, category, breakdown = scoring.criteria_score(_job(), _PROFILE, _CRITERIA)
    assert score is None and category is None
    assert "API down" in reason


def _fake_groq(captured):
    client = MagicMock()
    resp = MagicMock()
    resp.choices[0].message.content = '{"veto": null, "kriterien": {}}'

    def create(**kwargs):
        captured.update(kwargs)
        return resp
    client.chat.completions.create = create
    return client


class TestFewShotFeedback:
    def test_feedback_examples_in_prompt(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(scoring, "Groq", lambda api_key="": _fake_groq(captured))
        feedback = [{"vote": "up", "title": "Junior Unity Dev"},
                    {"vote": "down", "title": "Senior C++ Architekt"}]
        scoring.llm_criteria_eval(_job(), _PROFILE, _CRITERIA, feedback=feedback)
        user_msg = captured["messages"][1]["content"]
        assert "Junior Unity Dev" in user_msg
        assert "Senior C++ Architekt" in user_msg
        assert "FEEDBACK" in user_msg

    def test_max_five_examples_per_vote(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(scoring, "Groq", lambda api_key="": _fake_groq(captured))
        feedback = [{"vote": "up", "title": f"Liked {i}"} for i in range(7)]
        scoring.llm_criteria_eval(_job(), _PROFILE, _CRITERIA, feedback=feedback)
        user_msg = captured["messages"][1]["content"]
        assert "Liked 4" in user_msg
        assert "Liked 5" not in user_msg

    def test_prompt_unchanged_without_feedback(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(scoring, "Groq", lambda api_key="": _fake_groq(captured))
        scoring.llm_criteria_eval(_job(), _PROFILE, _CRITERIA)
        assert "FEEDBACK" not in captured["messages"][1]["content"]

    def test_criteria_score_passes_feedback_through(self, monkeypatch):
        seen = {}

        def fake_eval(job, prof, crits, feedback=None):
            seen["feedback"] = feedback
            return {"veto": None, "kriterien": {}}
        monkeypatch.setattr(scoring, "llm_criteria_eval", fake_eval)
        fb = [{"vote": "up", "title": "X"}]
        scoring.criteria_score(_job(), _PROFILE, _CRITERIA, feedback=fb)
        assert seen["feedback"] == fb
