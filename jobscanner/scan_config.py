"""Zentrale Preset-Quelle für Scan-Größen (klein/mittel/groß).

Nur die Owner-Ingestion (pipeline.run) konsumiert diese Presets. `member_max_jobs`
ist spec-treu definiert, wird aber vom Member-Pfad NICHT genutzt — die
Member-Scan-Größe ist das bestehende max_jobs-Select im Spar-Modus."""
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
