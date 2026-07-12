"""Matching & Scoring: Regel-Filter (No-Gos) + Groq-LLM-Bewertung gegen Nutzerprofil."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from groq import Groq

from jobscanner.models import Job

ENV_FILE = Path("/root/projekte/telegram-bot-army/.env")
_MODEL = "llama-3.1-8b-instant"  # 70b hatte 100k-TPD-Free-Tier-Deckel gesprengt (Learning 2026-07-12)

PASS_THRESHOLD = 70
MAYBE_THRESHOLD = 40

_NO_GO_PATTERNS = {
    "Senior-Stelle (5+ Jahre)": re.compile(
        r"\bsenior\b|\b[5-9]\+?\s*jahre\b|\bmehrj[aä]hrige\b", re.IGNORECASE),
    "Zeitarbeit/Personaldienstleister": re.compile(
        r"zeitarbeit|personaldienstleister|arbeitnehmer[uü]berlassung", re.IGNORECASE),
}


def _load_env() -> None:
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def rule_filter(job: Job) -> str | None:
    haystack = " ".join([job.title, job.employment_type, " ".join(job.requirements)])
    for label, pattern in _NO_GO_PATTERNS.items():
        if pattern.search(haystack):
            return label
    return None


def _category(score: int) -> str:
    if score >= PASS_THRESHOLD:
        return "Pass"
    if score >= MAYBE_THRESHOLD:
        return "Vielleicht"
    return "No-Go"


def llm_score(job: Job, profile: dict) -> tuple[int, str]:
    _load_env()
    client = Groq(api_key=os.environ.get("GROQ_API_KEY", ""))
    job_text = (
        f"Titel: {job.title}\nFirma: {job.company}\nOrt: {job.location}\n"
        f"Remote: {job.remote_flag}\nAnstellung: {job.employment_type}\n"
        f"Anforderungen: {', '.join(job.requirements)}\nTech-Stack: {', '.join(job.tech_stack)}"
    )
    profile_text = (
        f"Level: {profile.get('level')}\n"
        f"Erfahrung: {profile.get('experience_years')} Jahre "
        f"({', '.join(profile.get('experience_sources', []))})\n"
        f"Skills: {', '.join(profile.get('skills', []))}\n"
        f"Zielrollen: {', '.join(profile.get('target_roles', []))}\n"
        f"No-Gos: {', '.join(profile.get('no_gos', []))}"
    )
    resp = client.chat.completions.create(
        model=_MODEL,
        messages=[
            {"role": "system", "content": (
                "Du bewertest, wie gut eine Stellenanzeige zu einem Bewerberprofil passt. "
                "Antworte NUR im Format 'SCORE: <0-100>\nGRUND: <max 2 Saetze>'."
            )},
            {"role": "user", "content": f"PROFIL:\n{profile_text}\n\nJOB:\n{job_text}"},
        ],
        max_tokens=150,
    )
    content = resp.choices[0].message.content.strip()
    score = 0
    reason = content
    for line in content.splitlines():
        if line.upper().startswith("SCORE:"):
            digits = re.search(r"\d+", line)
            if digits:
                score = max(0, min(100, int(digits.group())))
        elif line.upper().startswith("GRUND:"):
            reason = line.split(":", 1)[1].strip()
    return score, reason


def score_job(job: Job, profile: dict) -> tuple[int | None, str, str | None]:
    no_go = rule_filter(job)
    if no_go:
        return 0, f"No-Go: {no_go}", "No-Go"
    try:
        score, reason = llm_score(job, profile)
    except Exception as exc:
        return None, f"Scoring-Fehler: {exc}", None
    return score, reason, _category(score)


def compute_weighted_score(breakdown: dict, criteria: list[dict]) -> int | None:
    """Normalisierte gewichtete Summe: Σ(p×w)/Σ(10×w)×100 über bewertbare Kriterien."""
    numerator = 0
    denominator = 0
    for crit in criteria:
        if crit["weight"] <= 0:
            continue
        entry = breakdown.get(crit["key"])
        if entry is None or entry.get("punkte") is None:
            continue
        punkte = max(0, min(10, int(entry["punkte"])))
        numerator += punkte * crit["weight"]
        denominator += 10 * crit["weight"]
    if denominator == 0:
        return None
    return round(numerator / denominator * 100)


def _feedback_block(feedback: list[dict] | None) -> str:
    """👍/👎-Feedback als Few-Shot-Beispiele — bis zu 5 Likes + 5 Dislikes."""
    if not feedback:
        return ""
    likes = [f["title"] for f in feedback if f["vote"] == "up"][:5]
    dislikes = [f["title"] for f in feedback if f["vote"] == "down"][:5]
    parts = []
    if likes:
        parts.append("Diese Jobs mochte der Nutzer: " + "; ".join(likes))
    if dislikes:
        parts.append("Diese Jobs lehnte der Nutzer ab: " + "; ".join(dislikes))
    if not parts:
        return ""
    return ("\n\nFEEDBACK ZU FRÜHEREN JOBS (Präferenz-Beispiele, bei der Bewertung "
            "berücksichtigen):\n" + "\n".join(parts))


def llm_criteria_eval(job: Job, profile_data: dict, criteria: list[dict],
                      feedback: list[dict] | None = None) -> dict:
    """Ein Groq-JSON-Call: bewertet alle Kriterien 0-10 (oder null) + Veto-Check."""
    _load_env()
    client = Groq(api_key=os.environ.get("GROQ_API_KEY", ""))
    job_text = (
        f"Titel: {job.title}\nFirma: {job.company}\nOrt: {job.location}\n"
        f"Remote: {job.remote_flag}\nAnstellung: {job.employment_type}\n"
        f"Sprache: {job.language}\nGehalt: {job.salary_text or 'keine Angabe'}\n"
        f"Anforderungen: {', '.join(job.requirements)}\nTech-Stack: {', '.join(job.tech_stack)}"
    )
    profile_text = "\n".join(f"{k}: {v}" for k, v in profile_data.items())
    criteria_text = "\n".join(
        f"- {c['key']}: {c['label']}" for c in criteria if c["weight"] > 0)
    no_gos = profile_data.get("no_gos", [])
    resp = client.chat.completions.create(
        model=_MODEL,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": (
                "Du bewertest eine Stellenanzeige gegen ein Bewerberprofil, Kriterium für "
                "Kriterium. Antworte NUR als JSON:\n"
                '{"veto": null | "<No-go-Text falls die Anzeige einem No-go des Profils '
                'entspricht>", "kriterien": {"<key>": {"punkte": 0-10 | null, '
                '"grund": "<max 1 Satz>"}}}\n'
                "punkte: 10 = perfekte Passung, 0 = klare Nichtpassung. "
                "null NUR wenn die Anzeige zu diesem Kriterium keine Information enthält. "
                "Bewerte JEDES gelistete Kriterium."
            )},
            {"role": "user", "content": (
                f"PROFIL:\n{profile_text}\n\nNO-GOS (Veto-Check):\n{', '.join(no_gos) or 'keine'}"
                f"\n\nKRITERIEN:\n{criteria_text}\n\nJOB:\n{job_text}"
                f"{_feedback_block(feedback)}")},
        ],
        max_tokens=1024,
    )
    return json.loads(resp.choices[0].message.content)


def criteria_score(job: Job, profile_data: dict, criteria: list[dict],
                   feedback: list[dict] | None = None) -> tuple[int | None, str, str | None, dict]:
    """Veto-Check (Regex-Fastpath + LLM) → gewichteter Score. Rückgabe:
    (score 0-100 | None, reason, category | None, breakdown)."""
    no_go = rule_filter(job)
    if no_go:
        return 0, f"No-Go: {no_go}", "No-Go", {}
    try:
        result = llm_criteria_eval(job, profile_data, criteria, feedback=feedback)
    except Exception as exc:
        return None, f"Scoring-Fehler: {exc}", None, {}
    if result.get("veto"):
        return 0, f"No-Go: {result['veto']}", "No-Go", {}
    breakdown = result.get("kriterien", {})
    score = compute_weighted_score(breakdown, criteria)
    if score is None:
        return None, "Keine bewertbaren Kriterien in der Anzeige", None, breakdown
    top = sorted(
        ((c["key"], breakdown.get(c["key"], {})) for c in criteria
         if breakdown.get(c["key"], {}).get("punkte") is not None),
        key=lambda kv: kv[1]["punkte"], reverse=True)[:2]
    reason = "; ".join(f"{k}: {v.get('grund', '')}" for k, v in top) or "bewertet"
    return score, reason, _category(score), breakdown
