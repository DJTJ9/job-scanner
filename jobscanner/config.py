"""YAML-Config-Loader — Profil, Query-Sets, Portal-Definitionen."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

_DIR = Path(__file__).parent
_PROFILES_DIR = _DIR / "profiles"
_QUERIES_FILE = _DIR / "queries.yaml"
_PORTALS_FILE = _DIR / "portals.yaml"
_ENV_FILE = Path("/root/projekte/telegram-bot-army/.env")

_PORTAL_REQUIRED = ("name", "site", "detail_url_pattern", "search_type")


def _load(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_profile(name: str = "default") -> dict:
    path = _PROFILES_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Profil '{name}' nicht gefunden: {path}")
    return _load(path)


def load_queries() -> dict:
    return _load(_QUERIES_FILE)


def load_portals() -> list[dict]:
    portals = _load(_PORTALS_FILE)
    for p in portals:
        missing = [k for k in _PORTAL_REQUIRED if not p.get(k)]
        if p.get("search_type") == "html" and not p.get("search_url_template"):
            missing.append("search_url_template")
        if missing:
            raise ValueError(f"Portal {p.get('name', '?')}: Pflichtfelder fehlen: {missing}")
    return portals


def _load_env() -> None:
    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def load_web_settings() -> dict:
    _load_env()
    return {
        "password": os.environ.get("JOBSCANNER_WEB_PASSWORD", ""),
        "session_secret": os.environ.get("JOBSCANNER_SESSION_SECRET", ""),
        "port": int(os.environ.get("JOBSCANNER_WEB_PORT", "8010")),
        "invite_code": os.environ.get("JOBSCANNER_INVITE_CODE", ""),
        "owner_email": os.environ.get("JOBSCANNER_OWNER_EMAIL", ""),
    }


def firecrawl_budget() -> int:
    """Firecrawl-Credit-Deckel pro Lauf (Volllauf-Vorbereitung 2026-07-11)."""
    return int(os.environ.get("JOBSCANNER_FC_BUDGET", "100"))
