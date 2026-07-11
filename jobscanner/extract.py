"""Playwright-Render + Groq-Extraktion + Normalisierung — Validierung lebt hier, nicht in storage."""
from __future__ import annotations

import json
import os
from pathlib import Path

from bs4 import BeautifulSoup
from groq import Groq

from jobscanner import browser
from jobscanner.models import Job

ENV_FILE = Path("/root/projekte/telegram-bot-army/.env")
_MODEL = "llama-3.1-8b-instant"
_MAX_CHARS = 8000  # Groq-TPM-Deckel (6.000 TPM auf llama-3.1-8b-instant) — Prompt klein halten

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
    resp = client.chat.completions.create(
        model=_MODEL,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
    )
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


def to_job(raw: dict, portal: str, url: str, today: str) -> Job | None:
    title = (raw.get("title") or "").strip()
    company = (raw.get("company") or "").strip()
    if not title or not company:
        return None
    remote = raw.get("remote") or "unknown"
    if remote not in ("onsite", "hybrid", "remote", "unknown"):
        remote = "unknown"
    return Job(
        title=title,
        company=company,
        location=(raw.get("location") or "").strip(),
        remote_flag=remote,
        employment_type=(raw.get("employment_type") or "").strip(),
        language=raw.get("language") or "",
        salary_text=(raw.get("salary") or "").strip(),
        requirements=[r for r in (raw.get("requirements") or []) if isinstance(r, str)],
        tech_stack=[t for t in (raw.get("tech_stack") or []) if isinstance(t, str)],
        sources=[{"portal": portal, "url": url, "found_at": today}],
        first_seen=today,
        last_seen=today,
    )
