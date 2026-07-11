"""Search-Layer: SearchProvider-Interface + Portal-Direct-Implementierungen.

Ersatz für Firecrawl (Credit-Blocker 2026-07): StepStone/Stellenanzeigen/Indeed
per Portal-Such-URL + BeautifulSoup-Link-Filter (Playwright-Render für JS-lastige
Seiten), Arbeitsagentur per öffentlicher JSON-API (bundesAPI/jobsuche-api).
Live-Recherche (Task 2) zeigte: StepStone/Stellenanzeigen.de liefern relative
hrefs, deshalb werden Links per urljoin gegen die gerenderte Seiten-URL aufgelöst.
"""
from __future__ import annotations

import re
from typing import Protocol
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

from jobscanner import browser

_TIMEOUT = 30
_ARBEITSAGENTUR_API = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobs"
_ARBEITSAGENTUR_HEADERS = {"X-API-Key": "jobboerse-jobsuche"}


class SearchProvider(Protocol):
    def search(self, query: str, limit: int = 10) -> list[str]: ...


class PortalSearchProvider:
    """HTML-Portale: Such-URL per Playwright rendern, Links per detail_url_pattern filtern.

    Findet die Suchseite keine Detail-Links direkt (nur Listing-/Pagination-Links),
    werden alle Links unfiltriert zurückgegeben — discover_urls() erkennt sie dann
    als Listings und expandiert sie per Links-Extraktion (siehe dortige Doku)."""

    def __init__(self, portal: dict):
        self.portal = portal

    def search(self, query: str, limit: int = 10) -> list[str]:
        url = self.portal["search_url_template"].format(query=quote_plus(query))
        html = browser.render(url)
        if html is None:
            return []
        pattern = re.compile(self.portal["detail_url_pattern"])
        all_links = _extract_links(html, url)
        detail = [u for u in all_links if pattern.search(u)]
        return (detail or all_links)[:limit]


class ArbeitsagenturSearchProvider:
    """Arbeitsagentur: öffentliche JSON-API statt HTML-Scrape."""

    def search(self, query: str, limit: int = 10) -> list[str]:
        try:
            resp = requests.get(_ARBEITSAGENTUR_API, headers=_ARBEITSAGENTUR_HEADERS,
                                params={"was": query, "size": limit}, timeout=_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException:
            return []
        stellen = resp.json().get("stellenangebote", [])
        return [f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{s['refnr']}"
                for s in stellen if s.get("refnr")][:limit]


def provider_for(portal: dict) -> SearchProvider:
    if portal.get("search_type") == "api":
        return ArbeitsagenturSearchProvider()
    return PortalSearchProvider(portal)


def _extract_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    urls = []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        if href not in seen:
            seen.add(href)
            urls.append(href)
    return urls


def _links_from_page(url: str, detail_url_pattern: str) -> list[str]:
    html = browser.render(url)
    if html is None:
        return []
    pattern = re.compile(detail_url_pattern)
    return [u for u in _extract_links(html, url) if pattern.search(u)]


def discover_urls(portal: dict, term: str, provider: SearchProvider,
                  limit: int = 10, min_detail: int = 5) -> list[str]:
    """Suche → Detail-URLs. Liefert die Suche zu wenige Detail-URLs,
    werden gefundene Listing-Seiten per Links-Expansion erweitert."""
    pattern = re.compile(portal["detail_url_pattern"])
    hits = provider.search(term, limit=limit)
    detail = [u for u in hits if pattern.search(u)]
    listings = [u for u in hits if not pattern.search(u)]
    for listing in listings:
        if len(detail) >= min_detail:
            break
        detail += [u for u in _links_from_page(listing, portal["detail_url_pattern"])
                   if u not in detail]
    seen: set[str] = set()
    return [u for u in detail if not (u in seen or seen.add(u))][:limit]
