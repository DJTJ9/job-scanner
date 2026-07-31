"""Prompt-Injection-Härtung: wrappt Fremdinhalt (Scrape-Herkunft) in XML-Delimiter,
damit LLM-Prompts Daten strukturell von Anweisungen trennen."""
from __future__ import annotations

UNTRUSTED_JOB_FIELDS = ("title", "company", "location", "remote_flag",
                        "employment_type", "requirements", "tech_stack")


def wrap_untrusted(value: str, tag: str = "job_data") -> str:
    """Wrappt value in <tag>…</tag>; entfernt Tag-Vorkommen im Content im Loop,
    bis keins mehr übrig ist (Single-Pass wäre per Verschachtelung umgehbar)."""
    open_tag, close_tag = f"<{tag}>", f"</{tag}>"
    safe = value
    while open_tag in safe or close_tag in safe:
        safe = safe.replace(close_tag, "").replace(open_tag, "")
    return f"{open_tag}\n{safe}\n{close_tag}"


def wrap_job_fields(item: dict) -> dict:
    """Kopie des Job-Dicts, Scrape-Felder (Strings + String-Listen) gewrappt;
    Server-Felder (fingerprint, profile_id, vote, …) bleiben unberührt."""
    out = dict(item)
    for key in UNTRUSTED_JOB_FIELDS:
        value = out.get(key)
        if isinstance(value, str) and value:
            out[key] = wrap_untrusted(value)
        elif isinstance(value, list):
            out[key] = [wrap_untrusted(v) if isinstance(v, str) else v for v in value]
    return out
