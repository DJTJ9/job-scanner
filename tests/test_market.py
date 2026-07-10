"""Tests für market.aggregate_skills/format_report — Markt-Aggregation (4.2)."""
from jobscanner import market
from jobscanner.models import Job


def _job(**overrides) -> Job:
    base = dict(title="Unity Developer", company="ACME", location="Hamburg",
                requirements=["Unity", "C#"], tech_stack=["Unity", "Git"], role="unity_games")
    base.update(overrides)
    return Job(**base)


def test_aggregate_skills_counts_across_all_jobs():
    jobs = [_job(requirements=["Unity", "C#"], tech_stack=["Git"]),
            _job(requirements=["Unity"], tech_stack=["Blender"])]
    result = market.aggregate_skills(jobs)
    counts = dict(result["gesamt"])
    assert counts["Unity"] == 2
    assert counts["Git"] == 1


def test_aggregate_skills_group_by_role_separates_groups():
    jobs = [
        _job(role="unity_games", requirements=[], tech_stack=["Unity"]),
        _job(role="ai_engineer", requirements=["Python"], tech_stack=[]),
    ]
    result = market.aggregate_skills(jobs, group_by_role=True)
    assert dict(result["unity_games"])["Unity"] == 1
    assert dict(result["ai_engineer"])["Python"] == 1
    assert "unity_games" in result and "ai_engineer" in result


def test_format_report_includes_group_names_and_counts():
    aggregate = {"gesamt": [("Unity", 3), ("C#", 2)]}
    text = market.format_report(aggregate)
    assert "gesamt" in text
    assert "Unity: 3" in text
