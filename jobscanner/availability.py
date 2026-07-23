"""Verfügbarkeits-Check: prüft alte Jobs an ihrer Quell-URL, markiert nicht mehr
ausgeschriebene per Soft-Mark status='expired'. Nur Playwright — NIE Firecrawl
(Credits nur für echtes Scraping, folgt der precheck.py-Doktrin). N=2-Strikes gegen
transiente Portal-Blocks: nur eindeutige Weg-Signale (404/410/Redirect/Textmarker)
treiben die Expiry.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from jobscanner import storage
from jobscanner.extract import _clean_text

_TIMEOUT_MS = 30000
_DEFAULT_DB = Path(__file__).parent.parent / "data" / "jobs.db"

# Eindeutige "Stelle ist weg"-Textmarker (case-insensitive, erweiterbar).
_GONE_MARKERS = (
    "nicht mehr verfügbar", "nicht mehr verfuegbar", "stelle wurde besetzt",
    "anzeige nicht gefunden", "diese stellenanzeige ist nicht mehr",
    "stellenanzeige nicht gefunden", "position has been filled",
    "job no longer available", "this job is no longer",
)
# Erkennbarer Job-Inhalt (aus precheck.py übernommen) — belegt "alive".
_CONTENT_KEYWORDS = (
    "anforderungen", "aufgaben", "ihr profil", "wir bieten", "bewerbung", "bewerben",
    "vollzeit", "teilzeit", "requirements", "responsibilities", "apply",
)
_MIN_CONTENT_HITS = 2


def _render_with_status(url: str) -> dict | None:
    """Wie browser.render(), behält aber das goto()-Response-Objekt, um HTTP-Status
    und finale (Redirect-)URL zu lesen. Gibt None bei Render-Fehler/Timeout."""
    try:
        with sync_playwright() as p:
            browser_obj = p.chromium.launch()
            page = browser_obj.new_page()
            resp = page.goto(url, timeout=_TIMEOUT_MS, wait_until="domcontentloaded")
            html = page.content()
            status = resp.status if resp is not None else 0
            final_url = page.url
            browser_obj.close()
            return {"status": status, "final_url": final_url, "html": html}
    except Exception:
        return None


def classify(detail_url: str, rendered: dict | None) -> str:
    """gone (eindeutiges Weg-Signal), alive (Status 200 + Job-Inhalt), unclear (sonst)."""
    if rendered is None:
        return "unclear"
    status = rendered.get("status", 0)
    if status in (404, 410):
        return "gone"
    text = _clean_text(rendered.get("html", ""))
    norm = text.lower()
    if any(marker in norm for marker in _GONE_MARKERS):
        return "gone"
    # Redirect weg von der Detail-Seite auf generische Listing-/Such-Seite.
    final_path = urlparse(rendered.get("final_url", "")).path.rstrip("/")
    detail_path = urlparse(detail_url).path.rstrip("/")
    if final_path and detail_path and final_path != detail_path:
        return "gone"
    if status == 200:
        hits = sum(1 for kw in _CONTENT_KEYWORDS if kw in norm)
        if hits >= _MIN_CONTENT_HITS:
            return "alive"
    return "unclear"


def check_all(older_than_days: int = 3, strikes: int = 2) -> dict:
    """Ein Lauf: alle Kandidaten prüfen, Strike-Zähler pflegen, bei `strikes`
    konsekutiven Weg-Signalen expiren."""
    candidates = storage.list_availability_candidates(older_than_days=older_than_days)
    result = {"checked": 0, "gone": 0, "alive": 0, "unclear": 0, "expired": 0}
    for cand in candidates:
        fp, url = cand["fingerprint"], cand["url"]
        verdict = classify(url, _render_with_status(url))
        result["checked"] += 1
        result[verdict] += 1
        if verdict == "gone":
            if storage.bump_unavailable_strike(fp) >= strikes:
                storage.mark_expired(fp)
                result["expired"] += 1
        elif verdict == "alive":
            storage.reset_unavailable_strike(fp)
        # unclear: Zähler bleibt unangetastet
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(_DEFAULT_DB))
    parser.add_argument("--older-than-days", type=int, default=3)
    parser.add_argument("--strikes", type=int, default=2)
    args = parser.parse_args()
    storage.init_db(args.db)
    report = check_all(older_than_days=args.older_than_days, strikes=args.strikes)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
