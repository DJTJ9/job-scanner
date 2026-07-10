"""Tests für Search-Layer — subprocess gemockt, kein Live-Firecrawl."""
from unittest.mock import patch, MagicMock

from jobscanner.search import FirecrawlSearchProvider, discover_urls

SEARCH_OUT = """\
Unity Developer Jobs und Stellenangebote - 2026 - Stepstone
  URL: https://www.stepstone.de/jobs/unity-developer
  Deine Karriere als Unity-Developer bietet vielfältige Entwicklungspfade.

Unity Developer (m/w/d) bei ACME
  URL: https://www.stepstone.de/stellenangebote--Unity-Developer-ACME--123-inline.html
  Wir suchen dich als Unity Developer.
"""

PORTAL = {"name": "stepstone", "site": "stepstone.de",
          "detail_url_pattern": r"stepstone\.de/stellenangebote--"}


def _proc(stdout: str) -> MagicMock:
    return MagicMock(returncode=0, stdout=stdout, stderr="")


class TestFirecrawlSearchProvider:
    def test_parses_url_lines(self):
        with patch("jobscanner.search.subprocess.run", return_value=_proc(SEARCH_OUT)) as run:
            urls = FirecrawlSearchProvider().search("Unity site:stepstone.de", limit=5)
        assert urls == [
            "https://www.stepstone.de/jobs/unity-developer",
            "https://www.stepstone.de/stellenangebote--Unity-Developer-ACME--123-inline.html",
        ]
        cmd = run.call_args[0][0]
        assert cmd[:2] == ["firecrawl", "search"]
        assert "--limit" in cmd and "5" in cmd

    def test_failed_call_returns_empty(self):
        with patch("jobscanner.search.subprocess.run",
                   return_value=MagicMock(returncode=1, stdout="", stderr="boom")):
            assert FirecrawlSearchProvider().search("x", limit=3) == []


class TestDiscoverUrls:
    def test_returns_only_detail_urls(self):
        with patch("jobscanner.search.subprocess.run", return_value=_proc(SEARCH_OUT)):
            urls = discover_urls(PORTAL, "Unity Entwickler Junior",
                                 FirecrawlSearchProvider(), limit=10, min_detail=1)
        assert urls == ["https://www.stepstone.de/stellenangebote--Unity-Developer-ACME--123-inline.html"]

    def test_expands_listing_pages_via_links_scrape(self):
        links_json = ('{"links": ['
                      '"https://www.stepstone.de/stellenangebote--Dev-Foo--1-inline.html",'
                      '"https://www.stepstone.de/cmp/de/acme",'
                      '"https://www.stepstone.de/stellenangebote--Dev-Bar--2-inline.html"]}')

        def fake_run(cmd, **kwargs):
            if cmd[1] == "search":
                return _proc(SEARCH_OUT)
            assert cmd[1] == "scrape" and "links" in cmd
            return _proc(links_json)

        with patch("jobscanner.search.subprocess.run", side_effect=fake_run):
            urls = discover_urls(PORTAL, "Unity", FirecrawlSearchProvider(),
                                 limit=10, min_detail=2)
        assert "https://www.stepstone.de/stellenangebote--Dev-Foo--1-inline.html" in urls
        assert "https://www.stepstone.de/stellenangebote--Dev-Bar--2-inline.html" in urls
        assert all("cmp/de" not in u for u in urls)
