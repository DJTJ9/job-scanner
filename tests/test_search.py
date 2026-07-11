"""Tests für Search-Layer — Playwright/Requests gemockt, kein Live-Call."""
from unittest.mock import patch, MagicMock

import requests

from jobscanner.search import (PortalSearchProvider, ArbeitsagenturSearchProvider,
                               discover_urls, provider_for)

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
