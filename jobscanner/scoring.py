"""Matching & Scoring: Regel-Filter (No-Gos) + gewichtete Kriterien-Formel.
Die eigentliche LLM-Bewertung passiert jetzt im Claude-Agent-Batch-Lauf
(llm_batch.py) — dieses Modul liefert nur noch die deterministischen,
Groq-freien Bausteine (Veto-Regex, Gewichtungsformel, Kategorie-Schwellen)."""
from __future__ import annotations

import re

from jobscanner.models import Job

PASS_THRESHOLD = 70
MAYBE_THRESHOLD = 40

_NO_GO_PATTERNS = {
    "Senior-Stelle (5+ Jahre)": re.compile(
        r"\bsenior\b|\b[5-9]\+?\s*jahre\b|\bmehrj[aä]hrige\b", re.IGNORECASE),
    "Zeitarbeit/Personaldienstleister": re.compile(
        r"zeitarbeit|personaldienstleister|arbeitnehmer[uü]berlassung", re.IGNORECASE),
}


def rule_filter(job: Job) -> str | None:
    haystack = " ".join([job.title, job.employment_type, " ".join(job.requirements)])
    for label, pattern in _NO_GO_PATTERNS.items():
        if pattern.search(haystack):
            return label
    return None


def category_for_score(score: int) -> str:
    if score >= PASS_THRESHOLD:
        return "Pass"
    if score >= MAYBE_THRESHOLD:
        return "Vielleicht"
    return "No-Go"


def compute_weighted_score(breakdown: dict, criteria: list[dict]) -> int | None:
    """Normalisierte gewichtete Summe: Σ(p×w)/Σ(10×w)×100 über bewertbare Kriterien."""
    numerator = 0
    denominator = 0
    for crit in criteria:
        if crit["weight"] <= 0:
            continue
        entry = breakdown.get(crit["key"])
        if entry is None or entry.get("punkte") is None:
            continue
        punkte = max(0, min(10, int(entry["punkte"])))
        numerator += punkte * crit["weight"]
        denominator += 10 * crit["weight"]
    if denominator == 0:
        return None
    return round(numerator / denominator * 100)


def top_reasons(breakdown: dict, criteria: list[dict], n: int = 2) -> str:
    """Formatiert die Top-n bewerteten Kriterien als Kurzbegründung."""
    top = sorted(
        ((c["key"], breakdown.get(c["key"], {})) for c in criteria
         if breakdown.get(c["key"], {}).get("punkte") is not None),
        key=lambda kv: kv[1]["punkte"], reverse=True)[:n]
    return "; ".join(f"{k}: {v.get('grund', '')}" for k, v in top) or "bewertet"
