"""Zentrale Preset-Quelle für Scan-Größen (klein/mittel/groß).

Nur die Owner-Ingestion (pipeline.run) konsumiert diese Presets. `member_max_jobs`
ist spec-treu definiert, wird aber vom Member-Pfad NICHT genutzt — die
Member-Scan-Größe ist das bestehende max_jobs-Select im Spar-Modus.
BROWSER_CAPS deckelt den residential Browser-Scan (get_scan_config)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScanPreset:
    limit_per_query: int
    max_scrapes_per_portal: int | None
    max_search_terms: int | None
    member_max_jobs: int | None


SCAN_PRESETS: dict[str, ScanPreset] = {
    "klein":  ScanPreset(5,  20,   3,    50),
    "mittel": ScanPreset(10, 60,   6,    150),
    "gross":  ScanPreset(15, None, None, None),
}


@dataclass(frozen=True)
class BrowserCaps:
    max_queries: int
    max_detail: int
    throttle_ms: int


BROWSER_CAPS: dict[str, BrowserCaps] = {
    "klein":  BrowserCaps(3, 20, 3000),
    "mittel": BrowserCaps(6, 60, 2000),
    "gross":  BrowserCaps(10, 120, 1500),
}


def browser_caps_for(max_jobs: int | None) -> BrowserCaps:
    """Browser-Scan-Caps aus dem Spar-Modus-max_jobs (kein eigenes Scan-Größe-Feld):
    ≤50 → klein, ≤150 → mittel, unbegrenzt/>150 → groß. Auch groß bleibt hart
    gedeckelt — ein Bann trifft die private Heim-IP des Runners."""
    if max_jobs is not None and max_jobs <= 50:
        return BROWSER_CAPS["klein"]
    if max_jobs is not None and max_jobs <= 150:
        return BROWSER_CAPS["mittel"]
    return BROWSER_CAPS["gross"]
