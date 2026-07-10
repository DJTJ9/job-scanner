"""Tests für scoring — rule_filter deterministisch, llm_score gemockt."""
import pytest

import jobscanner.scoring as scoring
from jobscanner.models import Job


def _job(**overrides) -> Job:
    base = dict(title="Unity Developer", company="ACME GmbH", location="Hamburg",
                employment_type="Vollzeit", requirements=["Unity", "C#"],
                tech_stack=["Unity", "C#"])
    base.update(overrides)
    return Job(**base)


_PROFILE = {
    "skills": ["Unity", "C#"],
    "target_roles": ["Unity/Games Programmer"],
    "experience_years": 2,
    "experience_sources": ["Eigene Projekte"],
    "no_gos": ["Senior-Stellen (5+ Jahre)", "Zeitarbeit/Personaldienstleister"],
}


def test_rule_filter_flags_senior_in_title():
    job = _job(title="Senior Unity Developer")
    assert scoring.rule_filter(job) == "Senior-Stelle (5+ Jahre)"


def test_rule_filter_flags_zeitarbeit_in_employment_type():
    job = _job(employment_type="Zeitarbeit")
    assert scoring.rule_filter(job) == "Zeitarbeit/Personaldienstleister"


def test_rule_filter_passes_junior_job():
    job = _job(title="Junior Unity Developer")
    assert scoring.rule_filter(job) is None


def test_score_job_skips_llm_call_on_no_go(monkeypatch):
    called = []
    monkeypatch.setattr(scoring, "llm_score", lambda job, profile: called.append(1))
    job = _job(title="Senior Unity Developer")
    score, reason, category = scoring.score_job(job, _PROFILE)
    assert score == 0
    assert category == "No-Go"
    assert "Senior" in reason
    assert called == []


def test_score_job_uses_llm_result_when_no_rule_match(monkeypatch):
    monkeypatch.setattr(scoring, "llm_score", lambda job, profile: (85, "Guter Fit"))
    job = _job()
    score, reason, category = scoring.score_job(job, _PROFILE)
    assert (score, reason, category) == (85, "Guter Fit", "Pass")


def test_score_job_maps_thresholds_to_category(monkeypatch):
    for value, expected in [(75, "Pass"), (55, "Vielleicht"), (10, "No-Go")]:
        monkeypatch.setattr(scoring, "llm_score", lambda job, profile, v=value: (v, "x"))
        _, _, category = scoring.score_job(_job(), _PROFILE)
        assert category == expected


def test_score_job_returns_none_score_on_llm_error(monkeypatch):
    def boom(job, profile):
        raise RuntimeError("groq down")
    monkeypatch.setattr(scoring, "llm_score", boom)
    score, reason, category = scoring.score_job(_job(), _PROFILE)
    assert score is None
    assert category is None
    assert "groq down" in reason


class FakeMessage:
    def __init__(self, content):
        self.content = content


class FakeChoice:
    def __init__(self, content):
        self.message = FakeMessage(content)


class FakeCompletion:
    def __init__(self, content):
        self.choices = [FakeChoice(content)]


class FakeCompletions:
    def __init__(self, content):
        self._content = content

    def create(self, **kwargs):
        return FakeCompletion(self._content)


class FakeChat:
    def __init__(self, content):
        self.completions = FakeCompletions(content)


class FakeGroqClient:
    def __init__(self, api_key=None, content="SCORE: 72\nGRUND: Guter Skill-Match"):
        self.chat = FakeChat(content)


def test_llm_score_parses_score_and_reason(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(scoring, "Groq", lambda api_key=None: FakeGroqClient(content="SCORE: 72\nGRUND: Guter Skill-Match"))
    score, reason = scoring.llm_score(_job(), _PROFILE)
    assert score == 72
    assert reason == "Guter Skill-Match"


def test_llm_score_clamps_out_of_range_score(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(scoring, "Groq", lambda api_key=None: FakeGroqClient(content="SCORE: 150\nGRUND: Zu hoch"))
    score, _ = scoring.llm_score(_job(), _PROFILE)
    assert score == 100
