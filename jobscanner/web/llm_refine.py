"""LLM-Verfeinerung im Profil-Wizard: Freitext/CV → Skill-/Rollen-Vorschläge + Startgewichte."""
from __future__ import annotations

import json
import os
from pathlib import Path

from groq import Groq

from jobscanner.storage import DEFAULT_CRITERIA

ENV_FILE = Path("/root/projekte/telegram-bot-army/.env")
_MODEL = "llama-3.3-70b-versatile"


def _load_env() -> None:
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def suggest_from_freetext(freetext: str) -> dict:
    """Ein Groq-JSON-Call: Skills, Nachbar-Zielrollen, Kriterien-Startgewichte aus Freitext/CV."""
    _load_env()
    client = Groq(api_key=os.environ.get("GROQ_API_KEY", ""))
    criteria_keys = ", ".join(c["key"] for c in DEFAULT_CRITERIA)
    resp = client.chat.completions.create(
        model=_MODEL,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": (
                "Du liest einen Freitext/Lebenslauf eines Jobsuchenden und schlägst Profildaten "
                "vor. Antworte NUR als JSON:\n"
                '{"skills": ["..."], "target_roles": ["..."], '
                '"criteria_weights": {"<key>": 0-5}}\n'
                f"Erlaubte Kriterien-Keys: {criteria_keys}. "
                "Nur Keys mit begründbarem Gewicht angeben, Rest weglassen."
            )},
            {"role": "user", "content": freetext},
        ],
        max_tokens=512,
    )
    return json.loads(resp.choices[0].message.content)
