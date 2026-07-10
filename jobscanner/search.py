"""Search-Layer: SearchProvider-Interface + Firecrawl-Implementierung.

firecrawl search gibt TEXT aus (Zeilen "  URL: <url>"), kein JSON — live
verifiziert gegen CLI 1.16.2. Exa bleibt als weiterer Provider nachrüstbar.
"""
from __future__ import annotations

import json
import re
import subprocess
from typing import Protocol

_URL_LINE = re.compile(r"^\s*URL:\s*(https?://\S+)", re.MULTILINE)
_TIMEOUT = 120


class SearchProvider(Protocol):
    def search(self, query: str, limit: int = 10) -> list[str]: ...


class FirecrawlSearchProvider:
    def search(self, query: str, limit: int = 10) -> list[str]:
        proc = subprocess.run(
            ["firecrawl", "search", query, "--limit", str(limit)],
            capture_output=True, text=True, timeout=_TIMEOUT,
        )
        if proc.returncode != 0:
            return []
        return _URL_LINE.findall(proc.stdout)


def _scrape_links(url: str) -> list[str]:
    proc = subprocess.run(
        ["firecrawl", "scrape", url, "-f", "links", "--json"],
        capture_output=True, text=True, timeout=_TIMEOUT,
    )
    if proc.returncode != 0:
        return []
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return []
    links = data.get("links", []) if isinstance(data, dict) else []
    return [l if isinstance(l, str) else l.get("url", "") for l in links]


def discover_urls(portal: dict, term: str, provider: SearchProvider,
                  limit: int = 10, min_detail: int = 5) -> list[str]:
    """Suche → Detail-URLs. Liefert die Suche zu wenige Detail-URLs,
    werden gefundene Listing-Seiten per Links-Scrape expandiert."""
    pattern = re.compile(portal["detail_url_pattern"])
    hits = provider.search(f"{term} site:{portal['site']}", limit=limit)
    detail = [u for u in hits if pattern.search(u)]
    listings = [u for u in hits if not pattern.search(u)]
    for listing in listings:
        if len(detail) >= min_detail:
            break
        detail += [u for u in _scrape_links(listing)
                   if pattern.search(u) and u not in detail]
    seen: set[str] = set()
    return [u for u in detail if not (u in seen or seen.add(u))][:limit]
