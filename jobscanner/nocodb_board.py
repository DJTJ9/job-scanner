"""NocoDB-Anzeige-Board: legt Tabelle 'Job Scanner Jobs' idempotent an und pusht Rows.

Credentials kommen aus telegram-bot-army/.env (gleiche Konvention wie die Hub-Scripts).
SQLite bleibt Quelle der Wahrheit — das Board ist reine Anzeige.
"""
from __future__ import annotations

import os
from pathlib import Path

import requests

from jobscanner.models import Job

ENV_FILE = Path("/root/projekte/telegram-bot-army/.env")
TABLE_TITLE = "Job Scanner Jobs"

_COLUMNS = [
    {"title": "Title", "uidt": "SingleLineText"},
    {"title": "Company", "uidt": "SingleLineText"},
    {"title": "Location", "uidt": "SingleLineText"},
    {"title": "Remote", "uidt": "SingleLineText"},
    {"title": "Status", "uidt": "SingleSelect",
     "dtxp": "'neu','interessant','beworben','interview','abgelehnt'"},
    {"title": "Score", "uidt": "Number"},
    {"title": "Quellen", "uidt": "LongText"},
    {"title": "First Seen", "uidt": "SingleLineText"},
]


def _load_env() -> None:
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def _cfg() -> tuple[str, str, str]:
    _load_env()
    url = os.environ.get("NOCODB_API_URL", "")
    token = os.environ.get("NOCODB_API_TOKEN", "")
    base = os.environ.get("NOCODB_BASE_ID", "")
    if not (url and token and base):
        raise RuntimeError("NocoDB-Credentials fehlen (NOCODB_API_URL/NOCODB_API_TOKEN/NOCODB_BASE_ID)")
    return url, token, base


def _headers(token: str) -> dict:
    return {"xc-token": token, "Content-Type": "application/json"}


def ensure_table() -> str:
    url, token, base = _cfg()
    r = requests.get(f"{url}/api/v1/db/meta/projects/{base}/tables", headers=_headers(token))
    r.raise_for_status()
    for table in r.json().get("list", []):
        if table.get("title") == TABLE_TITLE:
            return table["id"]
    r = requests.post(
        f"{url}/api/v1/db/meta/projects/{base}/tables",
        headers=_headers(token),
        json={"title": TABLE_TITLE, "columns": _COLUMNS},
    )
    r.raise_for_status()
    table_id = r.json().get("id", "")
    if not table_id:
        raise RuntimeError(f"Tabellen-Anlage fehlgeschlagen: {r.json()}")
    return table_id


def push_job(job: Job) -> int:
    table_id = ensure_table()
    url, token, _ = _cfg()
    payload = {
        "Title": job.title,
        "Company": job.company,
        "Location": job.location,
        "Remote": job.remote_flag,
        "Status": job.status,
        "Score": job.score,
        "Quellen": ", ".join(
            f"{s.get('portal', '?')}: {s.get('url', '')}" for s in job.sources
        ),
        "First Seen": job.first_seen,
    }
    payload = {k: v for k, v in payload.items() if v not in (None, "")}
    r = requests.post(f"{url}/api/v2/tables/{table_id}/records",
                      headers=_headers(token), json=payload)
    r.raise_for_status()
    return int(r.json()["Id"])
