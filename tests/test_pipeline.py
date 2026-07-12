"""Tests für Pipeline — nur noch Discover-Phase, kein Groq/Scoring/Report mehr im run()."""
import json
from unittest.mock import patch

import pytest

from jobscanner import pipeline, storage
from jobscanner.pipeline import run

PORTALS = [{"name": "indeed", "site": "indeed.de", "detail_url_pattern": "x",
           "search_type": "html", "search_url_template": "x"}]
QUERIES = {"unity_games": {"de": ["Unity Developer"]}}


class FakeProvider:
    def discover_urls(self, portal, term, limit=10):
        return [f"https://indeed.test/{term}-{i}" for i in range(2)]


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline.config, "load_portals", lambda: PORTALS)
    monkeypatch.setattr(pipeline.config, "load_queries", lambda: QUERIES)
    monkeypatch.setattr(pipeline.config, "load_profile", lambda name="default": {})
    monkeypatch.setattr(pipeline.neighbors, "get_neighbor_roles",
                        lambda profile, name, core, today=None: {})
    monkeypatch.setattr("jobscanner.browser.firecrawl_credits_ok", lambda: True)
    monkeypatch.setattr("jobscanner.browser.credits_remaining", lambda: None)
    yield tmp_path / "jobs.db"
    storage.close()


def _run(db_path, scrape_map, **kwargs):
    with patch("jobscanner.pipeline.extract.fetch_raw_text",
               side_effect=lambda url, **kw: scrape_map.get(url)):
        return pipeline.run(provider=FakeProvider(), db_path=db_path, today="2026-07-10",
                            **kwargs)


def test_first_run_stores_raw_jobs(env):
    with patch("jobscanner.search.discover_urls",
              return_value=["https://indeed.test/unity_games-Unity Developer-0"]):
        report = _run(env, {"https://indeed.test/unity_games-Unity Developer-0": "Rohtext"})
    assert report["new"] == 1
    storage.init_db(env)
    pending = storage.list_pending_extraction()
    assert len(pending) == 1
    assert pending[0]["raw_text"] == "Rohtext"


def test_second_run_same_day_reports_zero_new(env):
    url = "https://indeed.test/unity_games-Unity Developer-0"
    with patch("jobscanner.search.discover_urls", return_value=[url]):
        _run(env, {url: "Rohtext"})
        report = _run(env, {url: "Rohtext"})
    assert report["new"] == 0
    assert report["known_skipped"] == 1


def test_failed_fetch_counts_as_error_not_crash(env):
    url = "https://indeed.test/unity_games-Unity Developer-0"
    with patch("jobscanner.search.discover_urls", return_value=[url]):
        report = _run(env, {url: None})
    assert report["errors"] == 1
    assert report["new"] == 0


def test_max_scrapes_per_portal_caps_scraping(env):
    urls = [f"https://indeed.test/u-{i}" for i in range(5)]
    with patch("jobscanner.search.discover_urls", return_value=urls):
        report = _run(env, {u: "Text" for u in urls}, max_scrapes_per_portal=2)
    assert report["portals"]["indeed"]["scraped"] == 2


def test_run_sets_role_from_query_key(env):
    url = "https://indeed.test/unity_games-Unity Developer-0"
    with patch("jobscanner.search.discover_urls", return_value=[url]):
        _run(env, {url: "Rohtext"})
    storage.init_db(env)
    job = storage.list_pending_extraction()[0]
    # Role wird nicht über list_pending_extraction exponiert, sondern in der DB gehalten.
    raw = storage.get_job("nix")  # placeholder, siehe Note
    # Direktprüfung über Raw-SQL-Zeile:
    conn = storage._conn
    row = conn.execute("SELECT role FROM jobs WHERE fingerprint = ?",
                       (job["fingerprint"],)).fetchone()
    assert row["role"] == "unity_games"


def test_neighbor_role_jobs_get_is_neighbor_flag(env, monkeypatch):
    monkeypatch.setattr(pipeline.neighbors, "get_neighbor_roles",
                        lambda profile, name, core, today=None:
                        {"vr_games": {"terms": {"de": ["VR Developer"]}}})
    url = "https://indeed.test/vr_games-VR Developer-0"

    def discover(portal, term, provider, limit=10):
        # Term-abhängig, sonst würde die core-Rolle "unity_games" (dict-Reihenfolge
        # zuerst) dieselbe URL zuerst finden und als is_neighbor=False einbuchen.
        return [url] if term == "VR Developer" else []

    with patch("jobscanner.search.discover_urls", side_effect=discover):
        _run(env, {url: "Rohtext"})
    storage.init_db(env)
    job = storage.list_pending_extraction()[0]
    conn = storage._conn
    row = conn.execute("SELECT is_neighbor FROM jobs WHERE fingerprint = ?",
                       (job["fingerprint"],)).fetchone()
    assert bool(row["is_neighbor"]) is True


def test_run_writes_discover_report_json(env):
    url = "https://indeed.test/unity_games-Unity Developer-0"
    with patch("jobscanner.search.discover_urls", return_value=[url]), \
         patch.object(pipeline, "_REPORT_PATH", env.parent / "last_discover_report.json"):
        _run(env, {url: "Rohtext"})
        report_data = json.loads((env.parent / "last_discover_report.json").read_text())
    assert report_data["new"] == 1
    assert report_data["date"] == "2026-07-10"


class TestHybridRouting:
    def test_api_portal_uses_cached_description(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pipeline.config, "load_portals",
                            lambda: [{"name": "adzuna", "site": "x",
                                     "detail_url_pattern": "x", "search_type": "html",
                                     "search_url_template": "x", "detail_fetch": "api"}])
        monkeypatch.setattr(pipeline.config, "load_queries", lambda: QUERIES)
        monkeypatch.setattr(pipeline.config, "load_profile", lambda name="default": {})
        monkeypatch.setattr(pipeline.neighbors, "get_neighbor_roles",
                            lambda profile, name, core, today=None: {})
        monkeypatch.setattr("jobscanner.browser.firecrawl_credits_ok", lambda: True)
        monkeypatch.setattr("jobscanner.browser.credits_remaining", lambda: None)

        class ApiProvider:
            descriptions = {"https://adzuna.test/1": "Gecachte Beschreibung"}

        # search.discover_urls ruft intern provider.search() auf — ApiProvider hat
        # keins (Adzuna liefert URLs+Descriptions schon beim Discover), daher hier
        # wie in den anderen Tests auf Modulebene gepatcht.
        with patch("jobscanner.search.discover_urls",
                  return_value=["https://adzuna.test/1"]):
            pipeline.run(provider=ApiProvider(), db_path=tmp_path / "jobs.db",
                        today="2026-07-10")
        storage.init_db(tmp_path / "jobs.db")
        assert storage.list_pending_extraction()[0]["raw_text"] == "Gecachte Beschreibung"
        storage.close()


class TestIndeedThrottle:
    def test_canonicalized_url_dedups_within_run(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pipeline.config, "load_portals", lambda: PORTALS)
        monkeypatch.setattr(pipeline.config, "load_queries", lambda: QUERIES)
        monkeypatch.setattr(pipeline.config, "load_profile", lambda name="default": {})
        monkeypatch.setattr(pipeline.neighbors, "get_neighbor_roles",
                            lambda profile, name, core, today=None: {})
        monkeypatch.setattr("jobscanner.browser.firecrawl_credits_ok", lambda: True)
        monkeypatch.setattr("jobscanner.browser.credits_remaining", lambda: None)
        urls = ["https://de.indeed.com/viewjob?jk=abc&bb=1",
               "https://de.indeed.com/viewjob?jk=abc&bb=2"]
        with patch("jobscanner.search.discover_urls", return_value=urls), \
             patch("jobscanner.pipeline.extract.fetch_raw_text", return_value="Text"):
            report = pipeline.run(provider=FakeProvider(), db_path=tmp_path / "jobs.db",
                                  today="2026-07-10")
        assert report["new"] == 1
        storage.close()
