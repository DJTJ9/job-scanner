"""Tests für scoring — rule_filter + category_for_score, deterministisch, kein LLM."""
import jobscanner.scoring as scoring
from jobscanner.models import Job


def _job(**overrides) -> Job:
    base = dict(title="Unity Developer", company="ACME GmbH", location="Hamburg",
                employment_type="Vollzeit", requirements=["Unity", "C#"],
                tech_stack=["Unity", "C#"])
    base.update(overrides)
    return Job(**base)


def test_rule_filter_flags_senior_in_title():
    job = _job(title="Senior Unity Developer")
    assert scoring.rule_filter(job) == "Senior-Stelle (5+ Jahre)"


def test_rule_filter_flags_zeitarbeit_in_employment_type():
    job = _job(employment_type="Zeitarbeit")
    assert scoring.rule_filter(job) == "Zeitarbeit/Personaldienstleister"


def test_rule_filter_passes_junior_job():
    job = _job(title="Junior Unity Developer")
    assert scoring.rule_filter(job) is None


def test_category_for_score_maps_thresholds():
    assert scoring.category_for_score(75) == "Pass"
    assert scoring.category_for_score(55) == "Vielleicht"
    assert scoring.category_for_score(10) == "No-Go"
