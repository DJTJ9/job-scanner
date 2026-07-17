"""Search-Layer: SearchProvider-Interface + Portal-Direct-Implementierungen.

Ersatz für Firecrawl (Credit-Blocker 2026-07): StepStone/Stellenanzeigen/Indeed
per Portal-Such-URL + BeautifulSoup-Link-Filter (Playwright-Render für JS-lastige
Seiten), Arbeitsagentur per öffentlicher JSON-API (bundesAPI/jobsuche-api).
Live-Recherche (Task 2) zeigte: StepStone/Stellenanzeigen.de liefern relative
hrefs, deshalb werden Links per urljoin gegen die gerenderte Seiten-URL aufgelöst.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Protocol
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

from jobscanner import browser

_TIMEOUT = 30
_ARBEITSAGENTUR_API = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobs"
_ARBEITSAGENTUR_HEADERS = {"X-API-Key": "jobboerse-jobsuche"}
_ADZUNA_API = "https://api.adzuna.com/v1/api/jobs/de/search/1"
_JOOBLE_API = "https://jooble.org/api/"
ENV_FILE = Path("/root/projekte/telegram-bot-army/.env")

_PLZ_RE = re.compile(r"\b\d{5}\b")
_DE_TOKEN_RE = re.compile(r"\bde\b")
_DE_CITIES = {
    "berlin", "hamburg", "münchen", "munich", "köln", "cologne", "frankfurt",
    "stuttgart", "düsseldorf", "dortmund", "essen", "leipzig", "bremen",
    "dresden", "hannover", "nürnberg", "duisburg", "bochum", "wuppertal",
    "bielefeld", "bonn", "münster", "karlsruhe", "mannheim", "augsburg",
    "wiesbaden", "mönchengladbach", "gelsenkirchen", "braunschweig",
    "chemnitz", "kiel", "aachen", "halle", "magdeburg", "freiburg",
    "krefeld", "lübeck", "mainz", "erfurt", "rostock", "kassel", "potsdam",
    "saarbrücken", "heidelberg", "darmstadt", "würzburg", "regensburg",
    "ingolstadt", "jena", "trier", "koblenz", "oldenburg", "osnabrück",
    "leverkusen", "wolfsburg", "göttingen", "reutlingen",
}


def classify_location(location: str) -> bool:
    """True = eindeutig nicht Deutschland ('Ausland'), False = DE oder uneindeutig.
    Uneindeutige Fälle (leer, 'Remote') gelten als DE — im Zweifel nicht verstecken."""
    norm = (location or "").strip().lower()
    if not norm or "remote" in norm or "home office" in norm or "homeoffice" in norm:
        return False
    if _PLZ_RE.search(norm):
        return False
    if "deutschland" in norm or "germany" in norm:
        return False
    if _DE_TOKEN_RE.search(norm):
        return False
    if any(city in norm for city in _DE_CITIES):
        return False
    return True


def _load_env() -> None:
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


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
        html = browser.fetch(url, method=self.portal.get("search_fetch", "playwright"),
                             failover=self.portal.get("firecrawl_failover", False),
                             cost=browser.FC_COST_SEARCH)
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


class AdzunaSearchProvider:
    """Adzuna-Aggregator-API — Description je URL gecacht, Detail-Phase braucht keinen Scrape."""

    def __init__(self):
        self.descriptions: dict[str, str] = {}

    def search(self, query: str, limit: int = 10) -> list[str]:
        _load_env()
        app_id = os.environ.get("ADZUNA_APP_ID", "")
        app_key = os.environ.get("ADZUNA_APP_KEY", "")
        if not app_id or not app_key:
            return []
        try:
            resp = requests.get(_ADZUNA_API, params={
                "app_id": app_id, "app_key": app_key,
                "what": query, "results_per_page": limit}, timeout=_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException:
            return []
        urls = []
        for r in resp.json().get("results", []):
            url = r.get("redirect_url")
            if not url:
                continue
            self.descriptions[url] = "\n".join(filter(None, [
                r.get("title", ""),
                (r.get("company") or {}).get("display_name", ""),
                (r.get("location") or {}).get("display_name", ""),
                r.get("description", "")]))
            urls.append(url)
        return urls[:limit]


class JoobleSearchProvider:
    """Jooble-Aggregator-API — POST mit Key in URL, Description-Cache wie Adzuna."""

    def __init__(self):
        self.descriptions: dict[str, str] = {}

    def search(self, query: str, limit: int = 10) -> list[str]:
        _load_env()
        key = os.environ.get("JOOBLE_API_KEY", "")
        if not key:
            return []
        try:
            resp = requests.post(_JOOBLE_API + key,
                                 json={"keywords": query, "location": "Deutschland"},
                                 timeout=_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException:
            return []
        urls = []
        for j in resp.json().get("jobs", []):
            url = j.get("link")
            if not url:
                continue
            self.descriptions[url] = "\n".join(filter(None, [
                j.get("title", ""), j.get("company", ""),
                j.get("location", ""), j.get("snippet", "")]))
            urls.append(url)
        return urls[:limit]


def provider_for(portal: dict) -> SearchProvider:
    search_type = portal.get("search_type")
    if search_type == "api":
        return ArbeitsagenturSearchProvider()
    if search_type == "adzuna":
        return AdzunaSearchProvider()
    if search_type == "jooble":
        return JoobleSearchProvider()
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


def _links_from_page(url: str, portal: dict) -> list[str]:
    html = browser.fetch(url, method=portal.get("search_fetch", "playwright"),
                         failover=portal.get("firecrawl_failover", False),
                         cost=browser.FC_COST_SEARCH)
    if html is None:
        return []
    pattern = re.compile(portal["detail_url_pattern"])
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
        detail += [u for u in _links_from_page(listing, portal)
                   if u not in detail]
    seen: set[str] = set()
    return [u for u in detail if not (u in seen or seen.add(u))][:limit]
