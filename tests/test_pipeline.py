"""Tests für Pipeline-Kern — Fake-Provider, Extract + Board gemockt."""
from unittest.mock import MagicMock, patch

import pytest

from jobscanner import pipeline, storage
from jobscanner.pipeline import run

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
    monkeypatch.setattr(pipeline.config, "load_profile", lambda name="default": {})
    monkeypatch.setattr(pipeline.neighbors, "get_neighbor_roles",
                        lambda profile, name, core, today=None: {})
    monkeypatch.setattr(pipeline.scoring, "criteria_score",
                        lambda job, prof, crits, feedback=None: (50, "Test-Score", "Vielleicht",
                                                  {"role_fit": {"punkte": 5, "grund": "mock"}}))
    # Zentral gemockt: Report-Init ruft browser.firecrawl_credits_ok() —
    # ohne Patch würde jeder Test einen echten Subprocess-Call machen.
    monkeypatch.setattr("jobscanner.browser.firecrawl_credits_ok", lambda: True)
    monkeypatch.setattr("jobscanner.browser.credits_remaining", lambda: None)
    yield tmp_path / "jobs.db"
    storage.close()


def _run(db_path, scrape_map, push=False):
    with patch("jobscanner.pipeline.extract.scrape_job",
               side_effect=lambda url, **kwargs: scrape_map.get(url)):
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
               side_effect=lambda url, **kwargs: scrape_map.get(url)):
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


def test_pass_category_job_gets_archived(env):
    pipeline.scoring.criteria_score = lambda job, prof, crits, feedback=None: (85, "Top-Fit", "Pass", {})
    with patch("jobscanner.pipeline.archive.save_snapshot", return_value="/tmp/x.md") as snap:
        _run(env, {"https://stepstone.de/job/a": RAW_A}, push=False)
    snap.assert_called_once()
    jobs = storage.list_jobs()
    assert jobs[0].archive_path == "/tmp/x.md"


def test_vielleicht_category_job_not_archived(env):
    with patch("jobscanner.pipeline.archive.save_snapshot") as snap:
        _run(env, {"https://stepstone.de/job/a": RAW_A}, push=False)
    snap.assert_not_called()


def test_run_sends_telegram_report_by_default(env):
    with patch("jobscanner.pipeline.subprocess.run") as run:
        _run(env, {"https://stepstone.de/job/a": RAW_A}, push=False)
    run.assert_called_once()
    args = run.call_args[0][0]
    assert "telegram_notify.py" in args[1]


def test_run_skips_report_when_disabled(env):
    with patch("jobscanner.pipeline.subprocess.run") as run:
        with patch("jobscanner.pipeline.extract.scrape_job",
                   side_effect=lambda url, **kwargs: {"https://stepstone.de/job/a": RAW_A}.get(url)):
            pipeline.run(provider=FakeProvider(), db_path=env, push_nocodb=False,
                        today="2026-07-10", send_report=False)
    run.assert_not_called()


def test_uses_portal_specific_provider_when_none_passed(env, monkeypatch):
    calls = []

    class SpyProvider:
        def search(self, query, limit=10):
            calls.append(query)
            return ["https://stepstone.de/job/a"]

    monkeypatch.setattr(pipeline.search, "provider_for", lambda portal: SpyProvider())
    with patch("jobscanner.pipeline.extract.scrape_job",
               side_effect=lambda url, **kwargs: RAW_A):
        pipeline.run(provider=None, db_path=env, push_nocodb=False, today="2026-07-10")
    assert calls  # provider_for wurde tatsächlich benutzt


class TestHybridRouting:
    def test_api_portal_extracts_from_cached_description(self, tmp_path):
        portal = {"name": "adzuna", "site": "adzuna.de",
                  "detail_url_pattern": r"adzuna\.de/land/ad/",
                  "search_type": "adzuna", "detail_fetch": "api"}
        provider = MagicMock()
        provider.search.return_value = ["https://www.adzuna.de/land/ad/1"]
        provider.descriptions = {"https://www.adzuna.de/land/ad/1": "Junior Unity Dev\nACME\nHamburg"}
        raw = {"title": "Junior Unity Dev", "company": "ACME", "location": "Hamburg"}
        with patch("jobscanner.pipeline.config.load_portals", return_value=[portal]), \
             patch("jobscanner.pipeline.config.load_queries",
                   return_value={"unity_games": {"de": ["Unity"]}}), \
             patch("jobscanner.pipeline.config.load_profile", return_value={}), \
             patch("jobscanner.pipeline.neighbors.get_neighbor_roles", return_value={}), \
             patch("jobscanner.pipeline.extract.extract_from_text", return_value=raw) as eft, \
             patch("jobscanner.pipeline.extract.scrape_job") as scrape, \
             patch("jobscanner.pipeline.scoring.criteria_score",
                   return_value=(50, "ok", "Vielleicht", {})), \
             patch("jobscanner.pipeline.browser.firecrawl_credits_ok", return_value=True):
            report = run(provider=provider, db_path=tmp_path / "t.db",
                         push_nocodb=False, send_report=False)
        eft.assert_called_once_with("Junior Unity Dev\nACME\nHamburg")
        scrape.assert_not_called()
        assert report["new"] == 1

    def test_scrape_portal_passes_fetch_method_and_failover(self, tmp_path):
        portal = {"name": "stellenanzeigen", "site": "stellenanzeigen.de",
                  "detail_url_pattern": r"stellenanzeigen\.de/job/",
                  "search_type": "html",
                  "search_url_template": "https://www.stellenanzeigen.de/suche/?fulltext={query}",
                  "firecrawl_failover": True}
        provider = MagicMock()
        provider.search.return_value = ["https://www.stellenanzeigen.de/job/1"]
        with patch("jobscanner.pipeline.config.load_portals", return_value=[portal]), \
             patch("jobscanner.pipeline.config.load_queries",
                   return_value={"unity_games": {"de": ["Unity"]}}), \
             patch("jobscanner.pipeline.config.load_profile", return_value={}), \
             patch("jobscanner.pipeline.neighbors.get_neighbor_roles", return_value={}), \
             patch("jobscanner.pipeline.extract.scrape_job", return_value=None) as scrape, \
             patch("jobscanner.pipeline.browser.firecrawl_credits_ok", return_value=True):
            run(provider=provider, db_path=tmp_path / "t.db",
                push_nocodb=False, send_report=False)
        assert scrape.call_args.kwargs["fetch_method"] == "playwright"
        assert scrape.call_args.kwargs["failover"] is True

    def test_capped_portal_fires_no_further_search(self, tmp_path):
        """Live-E2E 2026-07-11: gecapptes Portal löste noch eine Firecrawl-Suche aus
        (Cap-Check erst nach discover_urls) — kostete 5 Credits pro Lauf bei Indeed."""
        portal = {"name": "indeed", "site": "de.indeed.com",
                  "detail_url_pattern": r"de\.indeed\.com/viewjob",
                  "search_type": "html",
                  "search_url_template": "https://de.indeed.com/jobs?q={query}",
                  "search_fetch": "firecrawl", "detail_fetch": "firecrawl"}
        provider = MagicMock()
        provider.search.side_effect = [["https://de.indeed.com/viewjob?jk=1"],
                                       ["https://de.indeed.com/viewjob?jk=2"]]
        raw = {"title": "Dev", "company": "ACME", "location": "Essen"}
        with patch("jobscanner.pipeline.config.load_portals", return_value=[portal]), \
             patch("jobscanner.pipeline.config.load_queries",
                   return_value={"unity_games": {"de": ["Q1", "Q2"]}}), \
             patch("jobscanner.pipeline.config.load_profile", return_value={}), \
             patch("jobscanner.pipeline.neighbors.get_neighbor_roles", return_value={}), \
             patch("jobscanner.pipeline.extract.scrape_job", return_value=raw), \
             patch("jobscanner.pipeline.scoring.criteria_score",
                   return_value=(50, "ok", "Vielleicht", {})), \
             patch("jobscanner.pipeline.browser.firecrawl_credits_ok", return_value=True):
            report = run(provider=provider, db_path=tmp_path / "t.db",
                         push_nocodb=False, send_report=False,
                         max_scrapes_per_portal=1)
        assert report["portals"]["indeed"]["scraped"] == 1
        assert provider.search.call_count == 1

    def test_report_contains_firecrawl_status(self, tmp_path):
        with patch("jobscanner.pipeline.config.load_portals", return_value=[]), \
             patch("jobscanner.pipeline.config.load_queries", return_value={}), \
             patch("jobscanner.pipeline.config.load_profile", return_value={}), \
             patch("jobscanner.pipeline.neighbors.get_neighbor_roles", return_value={}), \
             patch("jobscanner.pipeline.browser.firecrawl_credits_ok", return_value=False):
            report = run(db_path=tmp_path / "t.db", push_nocodb=False, send_report=False)
        assert report["firecrawl_ok"] is False


def test_neighbor_role_jobs_get_is_neighbor_flag(env, monkeypatch):
    monkeypatch.setattr(pipeline.neighbors, "get_neighbor_roles",
                        lambda profile, name, core, today=None: {
                            "gameplay_engineer": {"terms": {"de": ["Gameplay Programmierer"], "en": []}}
                        })
    scrape_map = {
        "https://stepstone.de/job/a": RAW_A,
        "https://stepstone.de/job/b": RAW_B,
        "https://stepstone.de/job/neighbor": {"title": "Gameplay Coder", "company": "Gamma",
                                              "location": "Köln"},
    }

    class RoleAwareProvider:
        def search(self, query, limit=10):
            if "Gameplay" in query:
                return ["https://stepstone.de/job/neighbor"]
            return ["https://stepstone.de/job/a", "https://stepstone.de/job/b"]

    with patch("jobscanner.pipeline.extract.scrape_job",
               side_effect=lambda url, **kwargs: scrape_map.get(url)):
        pipeline.run(provider=RoleAwareProvider(), db_path=env, push_nocodb=False,
                    today="2026-07-10")
    jobs = storage.list_jobs()
    neighbor_job = next(j for j in jobs if j.role == "gameplay_engineer")
    assert neighbor_job.is_neighbor is True
    core_job = next(j for j in jobs if j.role == "unity_games")
    assert core_job.is_neighbor is False


def test_neighbor_roles_excluded_when_cache_empty(env):
    report = _run(env, {"https://stepstone.de/job/a": RAW_A})
    assert report["new"] == 1
    assert storage.list_jobs()[0].is_neighbor is False


def test_profile_name_passed_to_load_profile_and_neighbors(env, monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline.config, "load_profile", lambda name="default": calls.append(("profile", name)) or {})
    monkeypatch.setattr(pipeline.neighbors, "get_neighbor_roles",
                        lambda profile, name, core, today=None: calls.append(("neighbors", name)) or {})
    _run(env, {"https://stepstone.de/job/a": RAW_A})
    assert ("profile", "default") in calls
    assert ("neighbors", "default") in calls


def test_run_scores_all_active_profiles(env):
    """Nach run(): job_scores enthält einen Eintrag pro aktivem Profil je neuem Job."""
    report = _run(env, {"https://stepstone.de/job/a": RAW_A})
    profiles = storage.list_profiles(active_only=True)
    assert len(profiles) >= 1  # Tjark aus Auto-Migration
    jobs = storage.list_jobs()
    assert jobs, "Pipeline muss Jobs angelegt haben"
    for p in profiles:
        s = storage.get_job_score(p["id"], jobs[0].fingerprint)
        assert s is not None and s["score"] == 50
    assert report["profiles_scored"] == len(profiles)


def test_run_mirrors_default_profile_score_to_jobs_table(env):
    _run(env, {"https://stepstone.de/job/a": RAW_A})
    job = storage.list_jobs()[0]
    assert job.score == 50
    assert job.category == "Vielleicht"


def test_run_scores_second_active_profile(env):
    storage.init_db(env)
    pid = storage.create_profile("Testi", {"skills": ["Python"]})
    storage.save_criteria(pid, [{"key": "role_fit", "label": "Rolle", "weight": 5, "sort": 0}])
    _run(env, {"https://stepstone.de/job/a": RAW_A})
    job = storage.list_jobs()[0]
    assert storage.get_job_score(pid, job.fingerprint)["score"] == 50


class TestIndeedThrottle:
    PORTAL = {"name": "indeed", "site": "de.indeed.com",
              "detail_url_pattern": r"de\.indeed\.com/(viewjob|rc/clk)",
              "search_type": "html",
              "search_url_template": "https://de.indeed.com/jobs?q={query}",
              "search_fetch": "firecrawl", "detail_fetch": "firecrawl",
              "max_search_terms": 2, "skip_neighbor_roles": True}

    def _run(self, tmp_path, provider, queries, neighbors_map=None):
        raw = {"title": "Dev", "company": "ACME", "location": "Essen"}
        with patch("jobscanner.pipeline.config.load_portals", return_value=[self.PORTAL]), \
             patch("jobscanner.pipeline.config.load_queries", return_value=queries), \
             patch("jobscanner.pipeline.config.load_profile", return_value={}), \
             patch("jobscanner.pipeline.neighbors.get_neighbor_roles",
                   return_value=neighbors_map or {}), \
             patch("jobscanner.pipeline.extract.scrape_job", return_value=raw), \
             patch("jobscanner.pipeline.scoring.criteria_score",
                   return_value=(50, "ok", "Vielleicht", {})), \
             patch("jobscanner.pipeline.browser.firecrawl_credits_ok", return_value=True):
            return run(provider=provider, db_path=tmp_path / "t.db",
                       push_nocodb=False, send_report=False)

    def test_max_search_terms_caps_searches(self, tmp_path):
        provider = MagicMock()
        provider.search.side_effect = [
            [f"https://de.indeed.com/viewjob?jk=a{i}"] for i in range(9)]
        queries = {"unity_games": {"de": ["Q1", "Q2", "Q3", "Q4"]}}
        self._run(tmp_path, provider, queries)
        assert provider.search.call_count == 2

    def test_skip_neighbor_roles_searches_core_only(self, tmp_path):
        provider = MagicMock()
        provider.search.return_value = ["https://de.indeed.com/viewjob?jk=b1"]
        queries = {"unity_games": {"de": ["Q1"]}}
        neighbors_map = {"gameplay_engineer":
                         {"terms": {"de": ["Gameplay Programmierer"]}}}
        self._run(tmp_path, provider, queries, neighbors_map=neighbors_map)
        searched = [c.args[0] for c in provider.search.call_args_list]
        assert searched == ["Q1"]

    def test_canonicalized_url_dedups_within_run(self, tmp_path):
        provider = MagicMock()
        provider.search.side_effect = [
            ["https://de.indeed.com/viewjob?jk=abc123&bb=one"],
            ["https://de.indeed.com/rc/clk?jk=abc123&bb=two"]]
        queries = {"unity_games": {"de": ["Q1", "Q2"]}}
        report = self._run(tmp_path, provider, queries)
        assert report["portals"]["indeed"]["scraped"] == 1
        job = storage.list_jobs()[0]
        assert job.sources[0]["url"] == "https://de.indeed.com/viewjob?jk=abc123"


def test_report_contains_credit_block(env):
    report = _run(env, {"https://stepstone.de/job/a": RAW_A})
    assert report["credits"] == {"estimated": 0, "real": None, "budget": 100}


def test_report_measures_real_credit_usage(env, monkeypatch):
    remaining = MagicMock(side_effect=[4980, 4975])
    monkeypatch.setattr("jobscanner.browser.credits_remaining", remaining)
    report = _run(env, {"https://stepstone.de/job/a": RAW_A})
    assert report["credits"]["real"] == 5


def test_report_message_contains_top_matches_and_credits(env):
    with patch("jobscanner.pipeline.subprocess.run") as notify:
        _run(env, {"https://stepstone.de/job/a": RAW_A})
    msg = notify.call_args[0][0][2]
    assert "Top-Treffer" in msg
    assert "Unity Dev" in msg
    assert "Firecrawl" in msg


def test_credit_counter_reset_per_run(env, monkeypatch):
    from jobscanner import browser
    browser._credits_spent = 77
    report = _run(env, {"https://stepstone.de/job/a": RAW_A})
    assert report["credits"]["estimated"] == 0


def test_run_passes_feedback_to_scoring(env, monkeypatch):
    storage.init_db(env)
    pid = storage.migrate_yaml_profile()
    from jobscanner.models import Job
    old = Job(title="Alter Treffer", company="ACME", location="Hamburg",
              sources=[{"portal": "stepstone", "url": "https://stepstone.de/job/old",
                        "found_at": "2026-07-01"}],
              first_seen="2026-07-01", last_seen="2026-07-01")
    storage.upsert_job(old)
    storage.add_feedback(pid, old.fingerprint, "up")
    seen = {}

    def fake_criteria_score(job, prof, crits, feedback=None):
        seen["fb"] = feedback
        return (50, "ok", "Vielleicht", {})
    monkeypatch.setattr(pipeline.scoring, "criteria_score", fake_criteria_score)
    _run(env, {"https://stepstone.de/job/a": RAW_A})
    assert seen["fb"] == [{"vote": "up", "title": "Alter Treffer"}]


def test_scoring_error_not_persisted_for_retry(env, monkeypatch):
    """Groq-Fehler (z.B. Tages-Rate-Limit) darf keine job_scores-Zeile erzeugen —
    sonst wird der Job nie wieder nachgescored (Learning 2026-07-12: 231 verwaiste
    NULL-Zeilen aus einem Live-Lauf, der ohne diesen Guard lief)."""
    monkeypatch.setattr(pipeline.scoring, "criteria_score",
                        lambda job, prof, crits, feedback=None:
                        (None, "Scoring-Fehler: 429 rate limit", None, {}))
    report = _run(env, {"https://stepstone.de/job/a": RAW_A})
    assert report["new"] == 1
    fp = storage.list_jobs()[0].fingerprint
    pid = storage.migrate_yaml_profile()
    assert storage.get_job_score(pid, fp) is None
    assert storage.get_job(fp).score is None
