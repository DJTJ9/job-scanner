"""Firecrawl-Extraktion + Normalisierung — Validierung lebt hier, nicht in storage."""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from jobscanner.models import Job

_TIMEOUT = 180

# Einheitliches Extraktions-Schema — Felder aus models.Job abgeleitet.
# Gehalt ist optional (portalabhängig, Spike-Report 2026-07-09).
SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Jobtitel"},
        "company": {"type": "string", "description": "Firmenname"},
        "location": {"type": "string", "description": "Arbeitsort(e)"},
        "remote": {"type": "string", "enum": ["onsite", "hybrid", "remote", "unknown"],
                   "description": "Remote-Modell, unknown falls unklar"},
        "employment_type": {"type": "string", "description": "z.B. Vollzeit, Teilzeit, Festanstellung"},
        "language": {"type": "string", "enum": ["de", "en"], "description": "Sprache der Anzeige"},
        "salary": {"type": "string", "description": "Gehaltsangabe falls im Posting, sonst leer"},
        "requirements": {"type": "array", "items": {"type": "string"},
                         "description": "Anforderungen/Profil als Liste"},
        "tech_stack": {"type": "array", "items": {"type": "string"},
                       "description": "Technologien/Tools/Frameworks"},
    },
    "required": ["title", "company"],
}

_schema_file: Path | None = None


def _get_schema_file() -> Path:
    global _schema_file
    if _schema_file is None or not _schema_file.exists():
        f = tempfile.NamedTemporaryFile("w", suffix="_job_schema.json",
                                        delete=False, encoding="utf-8")
        json.dump(SCHEMA, f, ensure_ascii=False)
        f.close()
        _schema_file = Path(f.name)
    return _schema_file


def scrape_job(url: str) -> dict | None:
    proc = subprocess.run(
        ["firecrawl", "scrape", url, "-f", "json",
         "--schema-file", str(_get_schema_file()), "--json"],
        capture_output=True, text=True, timeout=_TIMEOUT,
    )
    if proc.returncode != 0:
        return None
    # CLI 1.16.2 druckt eine "Scrape ID: ..."-Zeile vor dem JSON (Hüllen-Check
    # 2026-07-10) — Präfix bis zur ersten geschweiften Klammer überspringen.
    start = proc.stdout.find("{")
    if start == -1:
        return None
    try:
        data = json.loads(proc.stdout[start:])
    except json.JSONDecodeError:
        return None
    raw = data.get("json") if isinstance(data, dict) else None
    return raw if isinstance(raw, dict) else None


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
