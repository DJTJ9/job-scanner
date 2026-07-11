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


def test_neighbor_stats_splits_core_and_neighbor_counts():
    jobs = [
        _job(is_neighbor=False, category="Pass"),
        _job(is_neighbor=False, category="Vielleicht"),
        _job(is_neighbor=True, category="Pass"),
        _job(is_neighbor=True, category="No-Go"),
    ]
    stats = market.neighbor_stats(jobs)
    assert stats == {"core_total": 2, "core_pass": 1, "neighbor_total": 2, "neighbor_pass": 1}


def test_format_report_appends_neighbor_summary_when_present():
    aggregate = {"gesamt": [("Unity", 3)]}
    stats = {"core_total": 5, "core_pass": 2, "neighbor_total": 3, "neighbor_pass": 1}
    text = market.format_report(aggregate, stats)
    assert "Nachbarfelder" in text
    assert "3" in text and "1" in text


def test_format_report_omits_neighbor_summary_when_no_neighbors():
    aggregate = {"gesamt": [("Unity", 3)]}
    stats = {"core_total": 5, "core_pass": 2, "neighbor_total": 0, "neighbor_pass": 0}
    text = market.format_report(aggregate, stats)
    assert "Nachbarfelder" not in text


def test_format_report_works_without_stats_argument():
    aggregate = {"gesamt": [("Unity", 3)]}
    text = market.format_report(aggregate)
    assert "Unity: 3" in text
