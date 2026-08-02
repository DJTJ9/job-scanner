"""Verfügbarkeits-Check: prüft alte Jobs an ihrer Quell-URL, markiert nicht mehr
ausgeschriebene per Soft-Mark status='expired'. Nur Playwright — NIE Firecrawl
(Credits nur für echtes Scraping, folgt der precheck.py-Doktrin). N=2-Strikes gegen
transiente Portal-Blocks: nur eindeutige Weg-Signale (404/410/Redirect/Textmarker)
treiben die Expiry.

# HINWEIS: classify() + Marker sind auch als portable Kopie im Home-Helper bob_pool_cleaner.py — diese Datei bleibt maßgeblich (Drift manuell gehalten).
"""
from __future__ import annotations

from urllib.parse import urlparse

from jobscanner import storage
from jobscanner.extract import _clean_text

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


def apply_verdict(fingerprint: str, verdict: str, strikes: int = 2) -> bool:
    """Wendet EIN eingeliefertes Verdict an: gone bumpt den Strike (expire bei
    >= strikes konsekutiven), alive resettet, unclear lässt den Zähler unberührt.
    Gibt True zurück, wenn dieser Aufruf die Stelle expired hat."""
    if verdict == "gone":
        if storage.bump_unavailable_strike(fingerprint) >= strikes:
            storage.mark_expired(fingerprint)
            return True
    elif verdict == "alive":
        storage.reset_unavailable_strike(fingerprint)
    return False
