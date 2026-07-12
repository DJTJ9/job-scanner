"""Tests für kriterienbasiertes Scoring — LLM gemockt, Formel deterministisch."""
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


def test_top_reasons_picks_two_highest_scored_criteria():
    breakdown = {"role_fit": {"punkte": 9, "grund": "Unity-Kernrolle"},
                "remote": {"punkte": 10, "grund": "voll remote"},
                "salary": {"punkte": 3, "grund": "unklar"}}
    reason = scoring.top_reasons(breakdown, _CRITERIA)
    assert "voll remote" in reason and "Unity-Kernrolle" in reason
    assert "unklar" not in reason


def test_top_reasons_falls_back_when_nothing_bewertbar():
    breakdown = {k["key"]: {"punkte": None, "grund": "?"} for k in _CRITERIA}
    assert scoring.top_reasons(breakdown, _CRITERIA) == "bewertet"
