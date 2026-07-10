"""Matching & Scoring: Regel-Filter (No-Gos) + Groq-LLM-Bewertung gegen Nutzerprofil."""
from __future__ import annotations

import os
import re
from pathlib import Path

from groq import Groq

from jobscanner.models import Job

ENV_FILE = Path("/root/projekte/telegram-bot-army/.env")
_MODEL = "llama-3.3-70b-versatile"

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
