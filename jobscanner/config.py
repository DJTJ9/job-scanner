"""YAML-Config-Loader — Profil, Query-Sets, Portal-Definitionen."""
from __future__ import annotations

from pathlib import Path

import yaml

_DIR = Path(__file__).parent
_PROFILE_FILE = _DIR / "profile.yaml"
_QUERIES_FILE = _DIR / "queries.yaml"
_PORTALS_FILE = _DIR / "portals.yaml"

_PORTAL_REQUIRED = ("name", "site", "detail_url_pattern", "search_type")


def _load(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_profile() -> dict:
    return _load(_PROFILE_FILE)


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
