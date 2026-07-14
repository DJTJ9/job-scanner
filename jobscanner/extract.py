"""Playwright-Render + Rohtext-Normalisierung — Extraktion selbst passiert jetzt im
Claude-Agent-Batch-Lauf (llm_batch.py), kein Groq-Call mehr in diesem Modul."""
from __future__ import annotations

from bs4 import BeautifulSoup

from jobscanner import browser
from jobscanner.models import Job

_MAX_CHARS = 8000  # Rohtext-Deckel — hält den Agent-Kontext pro Batch handhabbar


def _clean_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()
    lines = [l.strip() for l in soup.get_text(separator="\n").splitlines() if l.strip()]
    return "\n".join(lines)[:_MAX_CHARS]


def clean_api_text(text: str) -> str:
    """Für Portale mit `detail_fetch: api` — Beschreibung liegt schon als Text vor,
    nur Deckel + Whitespace-Trim nötig."""
    return text[:_MAX_CHARS].strip()


def fetch_raw_text(url: str, fetch_method: str = "playwright",
                   failover: bool = False) -> str | None:
    html = browser.fetch(url, method=fetch_method, failover=failover)
    if html is None:
        return None
    return _clean_text(html)


def _str_field(value) -> str:
    """LLM-Extraktion liefert Felder gelegentlich als Objekt statt String
    (Live-Volllauf 2026-07-12: company als JSON-Objekt) — nur echte Strings
    bzw. deren name-Key übernehmen."""
    if isinstance(value, dict):
        value = value.get("name")
    return value.strip() if isinstance(value, str) else ""


def to_job(raw: dict, portal: str, url: str, today: str) -> Job | None:
    title = _str_field(raw.get("title"))
    company = _str_field(raw.get("company"))
    if not title or not company:
        return None
    remote = raw.get("remote") or "unknown"
    if remote not in ("onsite", "hybrid", "remote", "unknown"):
        remote = "unknown"
    return Job(
        title=title,
        company=company,
        location=_str_field(raw.get("location")),
        remote_flag=remote,
        employment_type=_str_field(raw.get("employment_type")),
        language=raw.get("language") or "",
        salary_text=_str_field(raw.get("salary")),
        requirements=[r for r in (raw.get("requirements") or []) if isinstance(r, str)],
        tech_stack=[t for t in (raw.get("tech_stack") or []) if isinstance(t, str)],
        sources=[{"portal": portal, "url": url, "found_at": today}],
        first_seen=today,
        last_seen=today,
    )
