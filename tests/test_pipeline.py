"""Tests für Pipeline-Kern — Fake-Provider, Extract + Board gemockt."""
from unittest.mock import patch

import pytest

from jobscanner import pipeline, storage

PORTALS = [{"name": "stepstone", "site": "stepstone.de",
            "detail_url_pattern": r"stepstone\.de/job/"}]
QUERIES = {"unity_games": {"de": ["Unity Junior"]}}

RAW_A = {"title": "Unity Dev", "company": "ACME", "location": "Hamburg"}
RAW_B = {"title": "AI Engineer", "company": "Beta GmbH", "location": "Berlin"}


class FakeProvider:
    def search(self, query, limit=10):
        return ["https://stepstone.de/job/a", "https://stepstone.de/job/b"]


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline.config, "load_portals", lambda: PORTALS)
    monkeypatch.setattr(pipeline.config, "load_queries", lambda: QUERIES)
    monkeypatch.setattr(pipeline.config, "load_profile", lambda: {})
    monkeypatch.setattr(pipeline.scoring, "score_job",
                        lambda job, profile: (50, "Test-Score", "Vielleicht"))
    yield tmp_path / "jobs.db"
    storage.close()


def _run(db_path, scrape_map, push=False):
    with patch("jobscanner.pipeline.extract.scrape_job",
               side_effect=lambda url: scrape_map.get(url)):
        return pipeline.run(provider=FakeProvider(), db_path=db_path,
                            push_nocodb=push, today="2026-07-10")


def test_first_run_stores_new_jobs(env):
    report = _run(env, {"https://stepstone.de/job/a": RAW_A,
                        "https://stepstone.de/job/b": RAW_B})
    assert report["new"] == 2
    assert report["portals"]["stepstone"]["scraped"] == 2
    assert len(storage.list_jobs()) == 2


def test_second_run_same_day_reports_zero_new(env):
    scrape_map = {"https://stepstone.de/job/a": RAW_A,
                  "https://stepstone.de/job/b": RAW_B}
    _run(env, scrape_map)
    report = _run(env, scrape_map)
    assert report["new"] == 0            # Frische-Filter 1.5
    assert report["known_skipped"] == 2  # kein zweiter Scrape bekannter URLs


def test_failed_scrape_counts_as_error_not_crash(env):
    report = _run(env, {"https://stepstone.de/job/a": RAW_A,
                        "https://stepstone.de/job/b": None})
    assert report["new"] == 1
    assert report["errors"] == 1


def test_max_scrapes_per_portal_caps_scraping(env):
    scrape_map = {"https://stepstone.de/job/a": RAW_A,
                  "https://stepstone.de/job/b": RAW_B}
    with patch("jobscanner.pipeline.extract.scrape_job",
               side_effect=lambda url: scrape_map.get(url)):
        report = pipeline.run(provider=FakeProvider(), db_path=env,
                              push_nocodb=False, today="2026-07-10",
                              max_scrapes_per_portal=1)
    assert report["portals"]["stepstone"]["scraped"] == 1
    assert report["new"] == 1


def test_nocodb_push_only_for_new_jobs(env):
    scrape_map = {"https://stepstone.de/job/a": RAW_A,
                  "https://stepstone.de/job/b": RAW_B}
    with patch("jobscanner.pipeline.nocodb_board.push_job", return_value=77) as push:
        _run(env, scrape_map, push=True)
    assert push.call_count == 2
    jobs = storage.list_jobs()
    assert all(j.nocodb_row_id == 77 for j in jobs)


def test_run_scores_new_jobs(env):
    report = _run(env, {"https://stepstone.de/job/a": RAW_A,
                        "https://stepstone.de/job/b": RAW_B})
    assert report["new"] == 2
    jobs = storage.list_jobs()
    assert all(j.score == 50 and j.category == "Vielleicht" for j in jobs)


def test_nocodb_push_includes_score(env):
    with patch("jobscanner.pipeline.nocodb_board.push_job", return_value=77) as push:
        _run(env, {"https://stepstone.de/job/a": RAW_A}, push=True)
    pushed_job = push.call_args[0][0]
    assert pushed_job.score == 50


def test_run_sets_role_from_query_key(env):
    report = _run(env, {"https://stepstone.de/job/a": RAW_A,
                        "https://stepstone.de/job/b": RAW_B})
    assert report["new"] == 2
    jobs = storage.list_jobs()
    assert all(j.role == "unity_games" for j in jobs)
