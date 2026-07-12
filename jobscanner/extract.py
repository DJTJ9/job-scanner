"""Playwright-Render + Groq-Extraktion + Normalisierung — Validierung lebt hier, nicht in storage."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from bs4 import BeautifulSoup
from groq import Groq, RateLimitError

from jobscanner import browser
from jobscanner.models import Job

ENV_FILE = Path("/root/projekte/telegram-bot-army/.env")
_MODEL = "llama-3.1-8b-instant"
_MAX_CHARS = 8000  # Groq-TPM-Deckel (6.000 TPM auf llama-3.1-8b-instant) — Prompt klein halten
_RETRY_ATTEMPTS = 3
_RETRY_SLEEP_S = 15  # TPM-Fenster ist minütlich — 429er brauchen echte Wartezeit

_SYSTEM_PROMPT = (
    "Extrahiere Stellenanzeige-Daten aus dem folgenden Text als JSON-Objekt mit "
    "exakt diesen Feldern: title (Jobtitel), company (Firmenname), location "
    "(Arbeitsort), remote (onsite|hybrid|remote|unknown), employment_type "
    "(z.B. Vollzeit/Teilzeit/Festanstellung), language (de|en), salary "
    "(Gehaltsangabe falls vorhanden, sonst leerer String), requirements "
    "(Liste von Anforderungen/Profil-Punkten), tech_stack (Liste von "
    "Technologien/Tools/Frameworks). Fehlende Felder als leerer String bzw. "
    "leere Liste. Antworte NUR mit dem JSON-Objekt."
)


def _load_env() -> None:
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def _clean_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()
    lines = [l.strip() for l in soup.get_text(separator="\n").splitlines() if l.strip()]
    return "\n".join(lines)[:_MAX_CHARS]


def extract_from_text(text: str) -> dict | None:
    text = text[:_MAX_CHARS]
    if not text.strip():
        return None
    _load_env()
    client = Groq(api_key=os.environ.get("GROQ_API_KEY", ""))
    resp = None
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            resp = client.chat.completions.create(
                model=_MODEL,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
            )
            break
        except RateLimitError:
            # 429 TPM crashte am 2026-07-12 den kompletten Volllauf —
            # kurz warten, dann Job notfalls überspringen statt abbrechen.
            if attempt == _RETRY_ATTEMPTS - 1:
                return None
            time.sleep(_RETRY_SLEEP_S)
    try:
        data = json.loads(resp.choices[0].message.content)
    except (json.JSONDecodeError, IndexError, AttributeError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def scrape_job(url: str, fetch_method: str = "playwright",
               failover: bool = False) -> dict | None:
    html = browser.fetch(url, method=fetch_method, failover=failover)
    if html is None:
        return None
    return extract_from_text(_clean_text(html))


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
