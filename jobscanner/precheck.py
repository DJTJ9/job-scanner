"""Firecrawl-freier Kompatibilitäts-Check für Kandidaten-Portale (custom_portals).

Ruft NIE Firecrawl auf — genau das ist der Zweck des Tools (Kosten schon beim
Prüfen vermeiden, nicht erst beim laufenden Scan).
"""
from __future__ import annotations

from jobscanner import browser
from jobscanner.extract import _clean_text

_BLOCK_MARKERS = (
    "checking your browser", "cloudflare", "captcha", "access denied",
    "bitte aktivieren sie javascript", "enable javascript", "just a moment",
    "attention required",
)
_STRUCTURE_KEYWORDS = (
    "anforderungen", "aufgaben", "ihr profil", "wir bieten", "bewerbung",
    "vollzeit", "teilzeit", "requirements", "responsibilities", "apply now",
)
_MIN_STRUCTURE_HITS = 2
_MIN_TEXT_LEN = 200


def precheck_portal(url: str) -> dict:
    html = browser.render(url)
    if html is None:
        return {"rendered": False, "blocked": None, "structured": None,
                "compatible": False, "reason": "Playwright konnte die Seite nicht laden"}
    text = _clean_text(html)
    norm = text.lower()
    blocked = any(marker in norm for marker in _BLOCK_MARKERS) or len(text) < _MIN_TEXT_LEN
    hits = sum(1 for kw in _STRUCTURE_KEYWORDS if kw in norm)
    structured = not blocked and hits >= _MIN_STRUCTURE_HITS
    return {"rendered": True, "blocked": blocked, "structured": structured,
            "compatible": not blocked and structured,
            "text_len": len(text), "keyword_hits": hits}
