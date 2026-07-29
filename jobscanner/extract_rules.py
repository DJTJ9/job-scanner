"""LLM-freie Regel-Extraktion: baut ein Job aus einem push_jobs-Listing ohne LLM.
Gröber als die Claude-Extraktion (llm-frei, spec-konform) — title/company kommen als
Metadaten aus bob-scan (JSON-LD/Fallback), der Rest per Regex auf raw_text. Fehlt
title oder company, gibt to_job None zurück und der Job bleibt 'pending' fürs
optionale LLM-Upgrade via bob-score."""
from __future__ import annotations

import re

from jobscanner.models import Job

_MAX_REQ_LINES = 120


def _remote_flag(text: str) -> str:
    t = text.lower()
    if re.search(r"\b(100\s*%\s*remote|voll\s*remote|fully remote|remote möglich|remote-first)\b", t):
        return "remote"
    if re.search(r"\b(hybrid|teilweise remote|remote-anteil|mobiles arbeiten)\b", t):
        return "hybrid"
    if re.search(r"\b(vor ort|präsenz|reine bürotätigkeit|onsite|im büro)\b", t):
        return "onsite"
    return "unknown"


def _employment_type(text: str) -> str:
    t = text.lower()
    for pat, label in (
        (r"werkstudent", "Werkstudent"),
        (r"praktik", "Praktikum"),
        (r"teilzeit", "Teilzeit"),
        (r"vollzeit|full[- ]time", "Vollzeit"),
    ):
        if re.search(pat, t):
            return label
    return ""


def _language(text: str) -> str:
    t = text.lower()
    if re.search(r"\b(englischkenntnisse|english|fluent in english)\b", t) and not re.search(
            r"\b(deutschkenntnisse|deutsch)\b", t):
        return "en"
    if re.search(r"\b(deutschkenntnisse|fließend deutsch|sehr gute deutsch)\b", t):
        return "de"
    return ""


def to_job(listing: dict, today: str) -> Job | None:
    title = (listing.get("title") or "").strip()
    company = (listing.get("company") or "").strip()
    if not title or not company:
        return None
    raw = listing.get("raw_text") or ""
    requirements = [l.strip() for l in raw.splitlines() if l.strip()][:_MAX_REQ_LINES]
    return Job(
        title=title,
        company=company,
        location=(listing.get("location") or "").strip(),
        remote_flag=_remote_flag(raw),
        employment_type=_employment_type(raw),
        language=_language(raw),
        salary_text="",
        requirements=requirements,
        first_seen=today,
        last_seen=today,
    )
