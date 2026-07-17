"""LLM-Verfeinerung im Profil-Wizard: Freitext/CV → Skill-/Rollen-Vorschläge + Startgewichte."""
from __future__ import annotations

from jobscanner.claude_llm import claude_json
from jobscanner.storage import DEFAULT_CRITERIA


def suggest_from_freetext(freetext: str) -> dict:
    """Ein claude_json-Call: Skills, Nachbar-Zielrollen, Kriterien-Startgewichte aus Freitext/CV."""
    criteria_keys = ", ".join(c["key"] for c in DEFAULT_CRITERIA)
    system = (
        "Du liest einen Freitext/Lebenslauf eines Jobsuchenden und schlägst Profildaten "
        "vor. Antworte NUR als JSON, ohne Vor-/Nachtext:\n"
        '{"skills": ["..."], "target_roles": ["..."], '
        '"criteria_weights": {"<key>": 0-5}}\n'
        f"Erlaubte Kriterien-Keys: {criteria_keys}. "
        "Nur Keys mit begründbarem Gewicht angeben, Rest weglassen."
    )
    return claude_json(system=system, prompt=freetext)
