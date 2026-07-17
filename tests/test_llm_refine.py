# tests/test_llm_refine.py
"""Tests für llm_refine.suggest_from_freetext — claude_json gemockt."""
from jobscanner.web import llm_refine


def test_suggest_from_freetext_returns_claude_json_output(monkeypatch):
    payload = {"skills": ["Python"], "target_roles": ["Backend"], "criteria_weights": {}}
    monkeypatch.setattr(llm_refine, "claude_json", lambda system, prompt: payload)
    assert llm_refine.suggest_from_freetext("5 Jahre Python") == payload


def test_suggest_from_freetext_passes_freetext_and_criteria_keys(monkeypatch):
    seen = {}

    def fake(system, prompt):
        seen["system"] = system
        seen["prompt"] = prompt
        return {}

    monkeypatch.setattr(llm_refine, "claude_json", fake)
    llm_refine.suggest_from_freetext("mein lebenslauf")
    assert seen["prompt"] == "mein lebenslauf"
    # System-Prompt listet die erlaubten Kriterien-Keys auf
    from jobscanner.storage import DEFAULT_CRITERIA
    assert DEFAULT_CRITERIA[0]["key"] in seen["system"]
