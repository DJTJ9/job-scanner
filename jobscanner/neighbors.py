"""Entdecker-Suchprofile: Groq-generierte Nachbarrollen mit Datei-Cache (TTL 7 Tage)."""
from __future__ import annotations

import datetime as _dt
import json
import os
from pathlib import Path

from groq import Groq

ENV_FILE = Path("/root/projekte/telegram-bot-army/.env")
_MODEL = "llama-3.3-70b-versatile"
_CACHE_FILE = Path(__file__).parent.parent / "data" / "neighbor_cache.json"
_TTL_DAYS = 7


def _load_env() -> None:
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def _read_cache(cache_path: Path) -> dict:
    if not cache_path.exists():
        return {}
    return json.loads(cache_path.read_text(encoding="utf-8"))


def _write_cache(cache_path: Path, cache: dict) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def _is_stale(entry: dict, today: str) -> bool:
    generated_at = entry.get("generated_at")
    if not generated_at:
        return True
    age = _dt.date.fromisoformat(today) - _dt.date.fromisoformat(generated_at)
    return age.days >= _TTL_DAYS


def generate_neighbor_roles(profile: dict, core_roles: set[str]) -> dict:
    _load_env()
    try:
        client = Groq(api_key=os.environ.get("GROQ_API_KEY", ""))
        profile_text = (
            f"Zielrollen: {', '.join(profile.get('target_roles', []))}\n"
            f"Skills: {', '.join(profile.get('skills', []))}"
        )
        resp = client.chat.completions.create(
            model=_MODEL,
            messages=[
                {"role": "system", "content": (
                    "Du schlägst semantisch verwandte Berufsrollen für ein Bewerberprofil vor. "
                    "Antworte NUR als JSON-Array, maximal 3 Einträge, Format: "
                    '[{"name": "kurzer_key", "terms": {"de": ["...", "..."], '
                    '"en": ["...", "..."]}}]. Maximal 2 Suchbegriffe pro Sprache.'
                )},
                {"role": "user", "content": profile_text},
            ],
            max_tokens=400,
        )
        content = resp.choices[0].message.content.strip()
        roles = json.loads(content)
    except Exception:
        return {}
    result: dict = {}
    for role in roles:
        name = role.get("name") if isinstance(role, dict) else None
        terms = role.get("terms") if isinstance(role, dict) else None
        if not name or name in core_roles or not terms:
            continue
        result[name] = {"terms": terms}
    return result


def get_neighbor_roles(profile: dict, profile_name: str, core_roles: set[str],
                        today: str | None = None,
                        cache_path: Path | None = None) -> dict:
    today = today or _dt.date.today().isoformat()
    cache_path = cache_path or _CACHE_FILE
    cache = _read_cache(cache_path)
    entry = cache.get(profile_name)
    if entry is None or _is_stale(entry, today):
        roles = generate_neighbor_roles(profile, core_roles)
        cache[profile_name] = {"generated_at": today, "roles": roles}
        _write_cache(cache_path, cache)
        return roles
    return entry.get("roles", {})
