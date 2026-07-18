"""Tests für Search-Layer — Playwright/Requests gemockt, kein Live-Call."""
from unittest.mock import patch, MagicMock

import requests

from jobscanner.search import (PortalSearchProvider, ArbeitsagenturSearchProvider,
                               discover_urls, provider_for, classify_location)
from jobscanner import browser

HTML = """
<html><body>
<a href="https://www.stepstone.de/stellenangebote--Unity-Developer-ACME--123-inline.html">Job</a>
<a href="https://www.stepstone.de/cmp/de/acme">Firma</a>
</body></html>
"""

RELATIVE_HTML = """
<html><body>
<a href="/stellenangebote--Unity-Developer-ACME--123-inline.html">Job</a>
<a href="/cmp/de/acme">Firma</a>
</body></html>
"""

PORTAL = {"name": "stepstone", "site": "stepstone.de",
          "detail_url_pattern": r"stepstone\.de/stellenangebote--",
          "search_type": "html",
          "search_url_template": "https://www.stepstone.de/jobs/{query}"}

ARBEITSAGENTUR = {"name": "arbeitsagentur", "site": "arbeitsagentur.de",
                  "detail_url_pattern": r"arbeitsagentur\.de/jobsuche/jobdetail/",
                  "search_type": "api"}


class TestPortalSearchProvider:
    def test_renders_search_url_and_filters_links(self):
        with patch("jobscanner.search.browser.render", return_value=HTML) as render:
            urls = PortalSearchProvider(PORTAL).search("Unity Entwickler", limit=5)
        assert urls == ["https://www.stepstone.de/stellenangebote--Unity-Developer-ACME--123-inline.html"]
        assert render.call_args[0][0] == "https://www.stepstone.de/jobs/Unity+Entwickler"

    def test_render_failure_returns_empty(self):
        with patch("jobscanner.search.browser.render", return_value=None):
            assert PortalSearchProvider(PORTAL).search("x") == []

    def test_resolves_relative_hrefs_to_absolute(self):
        # Live-Recherche (Task 2) zeigte: StepStone/Stellenanzeigen.de liefern
        # relative hrefs ("/stellenangebote--..."), nicht absolute URLs.
        with patch("jobscanner.search.browser.render", return_value=RELATIVE_HTML):
            urls = PortalSearchProvider(PORTAL).search("Unity Entwickler", limit=5)
        assert urls == ["https://www.stepstone.de/stellenangebote--Unity-Developer-ACME--123-inline.html"]


class TestArbeitsagenturSearchProvider:
    def test_parses_api_response_into_detail_urls(self):
        resp = MagicMock()
        resp.json.return_value = {"stellenangebote": [
            {"refnr": "10001-1002716922-S"}, {"refnr": "10001-1002716923-S"}]}
        resp.raise_for_status = MagicMock()
        with patch("jobscanner.search.requests.get", return_value=resp) as get:
            urls = ArbeitsagenturSearchProvider().search("Unity Entwickler", limit=10)
        assert urls == [
            "https://www.arbeitsagentur.de/jobsuche/jobdetail/10001-1002716922-S",
            "https://www.arbeitsagentur.de/jobsuche/jobdetail/10001-1002716923-S",
        ]
        assert get.call_args.kwargs["headers"] == {"X-API-Key": "jobboerse-jobsuche"}

    def test_request_failure_returns_empty(self):
        with patch("jobscanner.search.requests.get",
                   side_effect=requests.RequestException("boom")):
            assert ArbeitsagenturSearchProvider().search("x") == []


class TestProviderFor:
    def test_api_portal_gets_arbeitsagentur_provider(self):
        assert isinstance(provider_for(ARBEITSAGENTUR), ArbeitsagenturSearchProvider)

    def test_html_portal_gets_portal_provider(self):
        assert isinstance(provider_for(PORTAL), PortalSearchProvider)


class TestDiscoverUrls:
    def test_returns_only_detail_urls(self):
        with patch("jobscanner.search.browser.render", return_value=HTML):
            urls = discover_urls(PORTAL, "Unity Entwickler",
                                 PortalSearchProvider(PORTAL), limit=10, min_detail=1)
        assert urls == ["https://www.stepstone.de/stellenangebote--Unity-Developer-ACME--123-inline.html"]

    def test_expands_listing_pages_via_render(self):
        listing_html = '<a href="https://www.stepstone.de/jobs/liste-1">Listing</a>'
        detail_html = ('<a href="https://www.stepstone.de/stellenangebote--Dev-Foo--1-inline.html">Job</a>'
                       '<a href="https://www.stepstone.de/stellenangebote--Dev-Bar--2-inline.html">Job</a>')
        with patch("jobscanner.search.browser.render", side_effect=[listing_html, detail_html]):
            urls = discover_urls(PORTAL, "Unity", PortalSearchProvider(PORTAL),
                                 limit=10, min_detail=2)
        assert "https://www.stepstone.de/stellenangebote--Dev-Foo--1-inline.html" in urls
        assert "https://www.stepstone.de/stellenangebote--Dev-Bar--2-inline.html" in urls

    def test_threads_location_to_provider(self):
        calls = {}

        class FakeProvider:
            def search(self, query, limit=10, location=None):
                calls["location"] = location
                return []

        discover_urls(PORTAL, "term", FakeProvider(), limit=5, location="Berlin")
        assert calls["location"] == "Berlin"


ADZUNA_PORTAL = {"name": "adzuna", "site": "adzuna.de",
                 "detail_url_pattern": r"adzuna\.(de|com)/(land/ad|details)/",
                 "search_type": "adzuna", "detail_fetch": "api"}

JOOBLE_PORTAL = {"name": "jooble", "site": "jooble.org",
                 "detail_url_pattern": r"jooble\.org/desc/",
                 "search_type": "jooble", "detail_fetch": "api"}

INDEED_FC_PORTAL = {"name": "indeed", "site": "de.indeed.com",
                    "detail_url_pattern": r"de\.indeed\.com/(viewjob|rc/clk)",
                    "search_type": "html",
                    "search_url_template": "https://de.indeed.com/jobs?q={query}",
                    "search_fetch": "firecrawl", "detail_fetch": "firecrawl"}


class TestAdzunaSearchProvider:
    def _resp(self):
        r = MagicMock()
        r.json.return_value = {"results": [{
            "title": "Junior Unity Developer",
            "company": {"display_name": "ACME GmbH"},
            "location": {"display_name": "Hamburg"},
            "description": "Unity, C#, 2 Jahre Erfahrung",
            "redirect_url": "https://www.adzuna.de/land/ad/123"}]}
        return r

    def test_returns_urls_and_caches_description(self, monkeypatch):
        from jobscanner.search import AdzunaSearchProvider
        monkeypatch.setenv("ADZUNA_APP_ID", "id123")
        monkeypatch.setenv("ADZUNA_APP_KEY", "key456")
        provider = AdzunaSearchProvider()
        with patch("jobscanner.search.requests.get", return_value=self._resp()):
            urls = provider.search("Unity Entwickler", limit=5)
        assert urls == ["https://www.adzuna.de/land/ad/123"]
        cached = provider.descriptions["https://www.adzuna.de/land/ad/123"]
        assert "Junior Unity Developer" in cached
        assert "ACME GmbH" in cached
        assert "Unity, C#" in cached

    def test_empty_without_keys(self, monkeypatch):
        from jobscanner.search import AdzunaSearchProvider
        monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
        monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)
        with patch("jobscanner.search._load_env"), \
             patch("jobscanner.search.requests.get") as get:
            assert AdzunaSearchProvider().search("x") == []
        get.assert_not_called()

    def test_empty_on_request_error(self, monkeypatch):
        from jobscanner.search import AdzunaSearchProvider
        monkeypatch.setenv("ADZUNA_APP_ID", "id123")
        monkeypatch.setenv("ADZUNA_APP_KEY", "key456")
        with patch("jobscanner.search.requests.get",
                   side_effect=requests.ConnectionError("boom")):
            assert AdzunaSearchProvider().search("x") == []

    def test_passes_location_as_where(self, monkeypatch):
        from jobscanner.search import AdzunaSearchProvider
        monkeypatch.setenv("ADZUNA_APP_ID", "id123")
        monkeypatch.setenv("ADZUNA_APP_KEY", "key456")
        with patch("jobscanner.search.requests.get", return_value=self._resp()) as get:
            AdzunaSearchProvider().search("Unity", limit=5, location="Berlin")
        assert get.call_args.kwargs["params"]["where"] == "Berlin"


class TestJoobleSearchProvider:
    def _resp(self):
        r = MagicMock()
        r.json.return_value = {"jobs": [{
            "title": "Junior AI Engineer", "company": "Beta UG",
            "location": "Berlin", "snippet": "Python, LLM-Tooling",
            "link": "https://jooble.org/desc/456"}]}
        return r

    def test_returns_urls_and_caches_description(self, monkeypatch):
        from jobscanner.search import JoobleSearchProvider
        monkeypatch.setenv("JOOBLE_API_KEY", "guid789")
        provider = JoobleSearchProvider()
        with patch("jobscanner.search.requests.post", return_value=self._resp()) as post:
            urls = provider.search("AI Engineer", limit=5)
        assert urls == ["https://jooble.org/desc/456"]
        assert "Junior AI Engineer" in provider.descriptions["https://jooble.org/desc/456"]
        assert post.call_args[0][0].endswith("guid789")

    def test_sends_deutschland_as_location_filter(self, monkeypatch):
        from jobscanner.search import JoobleSearchProvider
        monkeypatch.setenv("JOOBLE_API_KEY", "guid789")
        with patch("jobscanner.search.requests.post", return_value=self._resp()) as post:
            JoobleSearchProvider().search("AI Engineer", limit=5)
        assert post.call_args.kwargs["json"]["location"] == "Deutschland"

    def test_uses_location_param_not_hardcoded(self, monkeypatch):
        from jobscanner.search import JoobleSearchProvider
        monkeypatch.setenv("JOOBLE_API_KEY", "guid789")
        with patch("jobscanner.search.requests.post", return_value=self._resp()) as post:
            JoobleSearchProvider().search("AI Engineer", limit=5, location="Berlin")
        assert post.call_args.kwargs["json"]["location"] == "Berlin"

    def test_empty_without_key(self, monkeypatch):
        from jobscanner.search import JoobleSearchProvider
        monkeypatch.delenv("JOOBLE_API_KEY", raising=False)
        with patch("jobscanner.search._load_env"), \
             patch("jobscanner.search.requests.post") as post:
            assert JoobleSearchProvider().search("x") == []
        post.assert_not_called()


class TestProviderRouting:
    def test_provider_for_dispatch(self):
        from jobscanner.search import (AdzunaSearchProvider, JoobleSearchProvider)
        assert isinstance(provider_for(ADZUNA_PORTAL), AdzunaSearchProvider)
        assert isinstance(provider_for(JOOBLE_PORTAL), JoobleSearchProvider)
        assert isinstance(provider_for(ARBEITSAGENTUR), ArbeitsagenturSearchProvider)
        assert isinstance(provider_for(PORTAL), PortalSearchProvider)

    def test_portal_search_uses_fetch_with_method(self):
        with patch("jobscanner.search.browser.fetch", return_value=HTML) as fetch:
            PortalSearchProvider(INDEED_FC_PORTAL).search("Unity", limit=5)
        assert fetch.call_args.kwargs["method"] == "firecrawl"

    def test_portal_search_default_method_playwright(self):
        with patch("jobscanner.search.browser.fetch", return_value=HTML) as fetch:
            PortalSearchProvider(PORTAL).search("Unity", limit=5)
        assert fetch.call_args.kwargs["method"] == "playwright"


def test_portal_search_passes_search_cost_to_fetch():
    portal = {"name": "indeed", "detail_url_pattern": r"de\.indeed\.com/viewjob",
              "search_url_template": "https://de.indeed.com/jobs?q={query}",
              "search_fetch": "firecrawl"}
    with patch("jobscanner.search.browser.fetch", return_value=None) as fetch:
        PortalSearchProvider(portal).search("Unity")
    assert fetch.call_args.kwargs["cost"] == browser.FC_COST_SEARCH


class TestClassifyLocation:
    def test_plz_pattern_is_de(self):
        assert classify_location("22765 Hamburg") is False

    def test_de_city_is_de(self):
        assert classify_location("München") is False

    def test_deutschland_substring_is_de(self):
        assert classify_location("Berlin, Deutschland") is False

    def test_germany_substring_is_de(self):
        assert classify_location("Munich, Germany") is False

    def test_de_country_code_token_is_de(self):
        assert classify_location("Musterstadt, DE") is False

    def test_empty_is_de(self):
        assert classify_location("") is False

    def test_remote_is_de(self):
        assert classify_location("Remote") is False

    def test_foreign_city_without_digits_is_ausland(self):
        assert classify_location("New York") is True

    def test_foreign_country_is_ausland(self):
        assert classify_location("London, United Kingdom") is True
