"""Dedup-Hilfen: URL-Skip für bereits bekannte Quellen (1.4/1.5).

Fingerprint-Merge selbst passiert in storage.upsert_job — hier nur die
Erkennung, welche URLs schon im Bestand sind, um Scrapes zu sparen.
"""
from __future__ import annotations

import re

from jobscanner import storage


def known_source_urls() -> dict[str, str]:
    """Alle bekannten Quell-URLs → Fingerprint des zugehörigen Jobs."""
    mapping: dict[str, str] = {}
    for job in storage.list_jobs():
        for source in job.sources:
            url = source.get("url")
            if url:
                mapping[url] = job.fingerprint
    return mapping


def touch_known(fingerprint: str, today: str) -> None:
    """Wiederfund: nur last_seen aktualisieren, first_seen bleibt (Frische 1.5)."""
    storage.update_job(fingerprint, last_seen=today)


_INDEED_JK_RE = re.compile(r"[?&]jk=([0-9a-fA-F]+)")


def canonicalize_url(url: str, portal: str) -> str:
    """Portal-URLs auf stabilen Identitäts-Parameter reduzieren.

    Indeed: volatiler bb=-Tracking-Param erzeugte Doppel-Scrapes/-Zeilen
    (Learning 2026-07-11) — jk= ist der stabile Job-Key."""
    if portal == "indeed":
        m = _INDEED_JK_RE.search(url)
        if m:
            return f"https://de.indeed.com/viewjob?jk={m.group(1)}"
    return url
