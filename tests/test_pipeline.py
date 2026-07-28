"""Tests für Pipeline — nur noch Discover-Phase, kein Groq/Scoring/Report mehr im run()."""
import json
from unittest.mock import patch

import pytest

from jobscanner import pipeline, search, storage
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

    def discover(portal, term, provider, limit=10, location=None):
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


def test_member_profile_queries_merged_into_scan(env):
    storage.init_db(env)
    storage.create_profile("Member1", {}, queries={"backend_dev": {"alle": ["Backend Engineer"]}})
    url = "https://indeed.test/backend_dev-Backend Engineer-0"

    def discover(portal, term, provider, limit=10, location=None):
        return [url] if term == "Backend Engineer" else []

    with patch("jobscanner.search.discover_urls", side_effect=discover):
        _run(env, {url: "Rohtext"})
    storage.init_db(env)
    job = storage.list_pending_extraction()[0]
    conn = storage._conn
    row = conn.execute("SELECT role FROM jobs WHERE fingerprint = ?",
                       (job["fingerprint"],)).fetchone()
    assert row["role"] == "backend_dev"


def test_member_profile_queries_override_same_role_key(env):
    storage.init_db(env)
    storage.migrate_yaml_profile()  # Tjark-Default-Profil zuerst anlegen (reale Bootstrap-Reihenfolge:
    # niedrigere id als Member-Profile, sonst würde Tjarks core-Query-Kopie das Member-Override
    # per id-Reihenfolge zurücküberschreiben — pipeline.run() ruft migrate_yaml_profile() ohnehin
    # idempotent selbst auf, hier nur vorgezogen für deterministische id-Reihenfolge im Test)
    storage.create_profile("Member2", {}, queries={"unity_games": {"alle": ["Custom Override Term"]}})
    url = "https://indeed.test/unity_games-Custom Override Term-0"

    def discover(portal, term, provider, limit=10, location=None):
        return [url] if term == "Custom Override Term" else []

    with patch("jobscanner.search.discover_urls", side_effect=discover):
        _run(env, {url: "Rohtext"})
    storage.init_db(env)
    assert len(storage.list_pending_extraction()) == 1


def test_profile_without_queries_unaffected(env):
    storage.init_db(env)
    storage.create_profile("Member3", {})
    url = "https://indeed.test/unity_games-Unity Developer-0"
    with patch("jobscanner.search.discover_urls", return_value=[url]):
        _run(env, {url: "Rohtext"})
    storage.init_db(env)
    assert len(storage.list_pending_extraction()) == 1


def test_run_writes_discover_report_json(env):
    url = "https://indeed.test/unity_games-Unity Developer-0"
    with patch("jobscanner.search.discover_urls", return_value=[url]), \
         patch.object(pipeline, "_REPORT_PATH", env.parent / "last_discover_report.json"):
        _run(env, {url: "Rohtext"})
        report_data = json.loads((env.parent / "last_discover_report.json").read_text())
    assert report_data["new"] == 1
    assert report_data["date"] == "2026-07-10"


def test_active_career_page_custom_portal_is_fetched(env):
    storage.init_db(env)
    uid = storage.create_user("m@test.de", "pw", role="member")
    pid = storage.create_custom_portal("https://foo.test/karriere", "career_page", uid)
    storage.activate_custom_portal(pid)
    storage.close()
    # Neu: Career-Page → Link-Following → Detail-Rohtext (statt Career-Page-URL selbst).
    detail = "https://foo.test/jobs/unity-dev"
    with patch("jobscanner.search.discover_urls", return_value=[]), \
         patch("jobscanner.pipeline.career_pages.discover_job_urls",
               return_value=[detail]):
        report = _run(env, {detail: "Karriereseite Rohtext"})
    storage.init_db(env)
    pending = storage.list_pending_extraction()
    assert any(p["raw_text"] == "Karriereseite Rohtext" for p in pending)


def test_active_portal_custom_portal_joins_search_loop(env):
    storage.init_db(env)
    uid = storage.create_user("m@test.de", "pw", role="member")
    pid = storage.create_custom_portal(
        "https://bar.test/jobs", "portal", uid,
        search_url_template="https://bar.test/jobs?q={query}",
        detail_url_pattern=r"bar\.test/jobs/\d+")
    storage.activate_custom_portal(pid)
    storage.close()
    url = "https://bar.test/jobs/123"
    with patch("jobscanner.search.discover_urls", return_value=[url]):
        report = _run(env, {url: "Rohtext"})
    assert f"custom:{pid}" in report["portals"]


def test_language_filter_skips_unselected_lang(env, monkeypatch):
    monkeypatch.setattr(pipeline.config, "load_queries",
                        lambda: {"unity_games": {"de": ["Unity Entwickler Junior"],
                                                 "en": ["Junior Unity Developer"]}})
    seen_terms = []

    def fake_discover(portal, term, provider, limit=10, location=None):
        seen_terms.append(term)
        return []

    monkeypatch.setattr(search, "discover_urls", fake_discover)
    _run(env, {}, languages={"de"})
    assert seen_terms, "es wurde überhaupt gesucht"
    assert "Unity Entwickler Junior" in seen_terms
    assert "Junior Unity Developer" not in seen_terms


def test_scan_size_klein_caps_scrapes(env, monkeypatch):
    urls = [f"https://x/{i}" for i in range(50)]
    monkeypatch.setattr(search, "discover_urls",
                        lambda *a, location=None, **k: urls)
    scrape_map = {u: "Rohtext" for u in urls}
    report = _run(env, scrape_map, scan_size="klein")
    for stats in report["portals"].values():
        assert stats["scraped"] <= 20  # klein.max_scrapes_per_portal


def test_location_threaded_to_discover(env, monkeypatch):
    seen = {}

    def fake_discover(portal, term, provider, limit=10, location=None):
        seen["location"] = location
        return []

    monkeypatch.setattr(search, "discover_urls", fake_discover)
    _run(env, {}, locations=["Berlin", "Remote"])
    assert seen["location"] == "Berlin"   # erste = primäre


def test_residential_portal_skipped_in_server_discover(env, monkeypatch):
    both = [{"name": "stepstone", "site": "stepstone.de", "detail_url_pattern": "x",
             "search_type": "html", "search_url_template": "x", "residential": True},
            *PORTALS]
    monkeypatch.setattr(pipeline.config, "load_portals", lambda: both)
    urls = [f"https://indeed.test/Unity Developer-{i}" for i in range(2)]
    scrape_map = {u: "Rohtext" for u in urls}
    with patch("jobscanner.search.discover_urls", return_value=urls):
        report = _run(env, scrape_map)
    assert "stepstone" not in report["portals"]      # residential raus
    assert report["portals"]["indeed"]["scraped"] == 2  # Rest unverändert


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


def test_career_page_yields_one_row_per_detail_url(env):
    cp = {"id": 7, "typ": "career_page", "url": "https://studio.de/karriere",
          "detail_url_pattern": None, "search_url_template": None}
    detail_a = "https://studio.de/jobs/unity-dev"
    detail_b = "https://studio.de/jobs/tech-artist"
    with patch("jobscanner.pipeline.storage.list_custom_portals", return_value=[cp]), \
         patch("jobscanner.pipeline.career_pages.discover_job_urls",
               return_value=[detail_a, detail_b]), \
         patch("jobscanner.search.discover_urls", return_value=[]), \
         patch("jobscanner.pipeline.extract.fetch_raw_text",
               side_effect=lambda u, **kw: f"Rohtext {u}"):
        report = pipeline.run(provider=FakeProvider(), db_path=env, today="2026-07-10")
    assert report["new"] == 2
    storage.init_db(env)
    # Zwei getrennte Raw-Zeilen mit je eigenem Fingerprint (Detail-URL):
    import sqlite3
    conn = sqlite3.connect(env)
    urls = {r[0] for r in conn.execute(
        "SELECT json_extract(value,'$.url') FROM jobs, "
        "json_each(jobs.sources_json)")}
    conn.close()
    assert detail_a in urls and detail_b in urls


_OPTIONAL_PORTALS = PORTALS + [
    {"name": "adzuna", "site": "adzuna.de", "detail_url_pattern": "x",
     "search_type": "html", "search_url_template": "x", "optional": True}]


def test_optional_source_enabled_reads_env(monkeypatch):
    from jobscanner import config
    monkeypatch.delenv("JOBSCANNER_ENABLE_ADZUNA", raising=False)
    assert config.optional_source_enabled("adzuna") is False
    monkeypatch.setenv("JOBSCANNER_ENABLE_ADZUNA", "1")
    assert config.optional_source_enabled("adzuna") is True
    monkeypatch.setenv("JOBSCANNER_ENABLE_ADZUNA", "0")
    assert config.optional_source_enabled("adzuna") is False


def test_optional_source_skipped_by_default(env, monkeypatch):
    monkeypatch.setattr(pipeline.config, "load_portals", lambda: _OPTIONAL_PORTALS)
    monkeypatch.delenv("JOBSCANNER_ENABLE_ADZUNA", raising=False)
    with patch("jobscanner.search.discover_urls", return_value=[]):
        report = _run(env, {})
    assert "adzuna" not in report["portals"]
    assert "indeed" in report["portals"]


def test_optional_source_enabled_by_flag(env, monkeypatch):
    monkeypatch.setattr(pipeline.config, "load_portals", lambda: _OPTIONAL_PORTALS)
    monkeypatch.setenv("JOBSCANNER_ENABLE_ADZUNA", "1")
    with patch("jobscanner.search.discover_urls", return_value=[]):
        report = _run(env, {})
    assert "adzuna" in report["portals"]


def test_career_page_skips_known_detail_url(env):
    cp = {"id": 7, "typ": "career_page", "url": "https://studio.de/karriere",
          "detail_url_pattern": None, "search_url_template": None}
    detail = "https://studio.de/jobs/unity-dev"
    # detail bereits als bekannt (z.B. von StepStone) → kein zweiter Insert.
    with patch("jobscanner.pipeline.storage.list_custom_portals", return_value=[cp]), \
         patch("jobscanner.pipeline.career_pages.discover_job_urls", return_value=[detail]), \
         patch("jobscanner.pipeline.dedup.known_source_urls", return_value={detail: "fp0"}), \
         patch("jobscanner.search.discover_urls", return_value=[]), \
         patch("jobscanner.pipeline.extract.fetch_raw_text",
               side_effect=lambda u, **kw: f"Rohtext {u}"):
        report = pipeline.run(provider=FakeProvider(), db_path=env, today="2026-07-10")
    assert report["new"] == 0
