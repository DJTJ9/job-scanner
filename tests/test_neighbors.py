"""Tests für neighbors.py — Groq-Nachbarrollen-Generierung + Cache mit TTL."""
import json

import pytest

from jobscanner import neighbors


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
    def __init__(self, api_key=None, content="[]"):
        self.chat = FakeChat(content)


_PROFILE = {"target_roles": ["Unity/Games Programmer"], "skills": ["Unity", "C#"]}
_CORE_ROLES = {"unity_games", "ai_engineer", "tools_workflow"}

_NEIGHBOR_JSON = json.dumps([
    {"name": "gameplay_engineer",
     "terms": {"de": ["Gameplay Programmierer"], "en": ["Gameplay Engineer"]}},
    {"name": "unity_games", "terms": {"de": ["Sollte gefiltert werden"], "en": []}},
])


def test_generate_neighbor_roles_parses_groq_json(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(neighbors, "Groq", lambda api_key=None: FakeGroqClient(content=_NEIGHBOR_JSON))
    result = neighbors.generate_neighbor_roles(_PROFILE, _CORE_ROLES)
    assert result["gameplay_engineer"]["terms"]["de"] == ["Gameplay Programmierer"]


def test_generate_neighbor_roles_filters_core_role_collisions(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(neighbors, "Groq", lambda api_key=None: FakeGroqClient(content=_NEIGHBOR_JSON))
    result = neighbors.generate_neighbor_roles(_PROFILE, _CORE_ROLES)
    assert "unity_games" not in result


def test_generate_neighbor_roles_returns_empty_on_invalid_json(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(neighbors, "Groq", lambda api_key=None: FakeGroqClient(content="kein json"))
    assert neighbors.generate_neighbor_roles(_PROFILE, _CORE_ROLES) == {}


def test_generate_neighbor_roles_returns_empty_on_api_error(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    class Boom:
        def __init__(self, api_key=None):
            raise RuntimeError("groq down")

    monkeypatch.setattr(neighbors, "Groq", Boom)
    assert neighbors.generate_neighbor_roles(_PROFILE, _CORE_ROLES) == {}


def test_get_neighbor_roles_generates_on_cache_miss(tmp_path, monkeypatch):
    monkeypatch.setattr(neighbors, "generate_neighbor_roles",
                        lambda profile, core: {"gameplay_engineer": {"terms": {"de": ["x"], "en": ["y"]}}})
    cache_path = tmp_path / "neighbor_cache.json"
    result = neighbors.get_neighbor_roles(_PROFILE, "default", _CORE_ROLES,
                                          today="2026-07-11", cache_path=cache_path)
    assert "gameplay_engineer" in result
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    assert cache["default"]["generated_at"] == "2026-07-11"


def test_get_neighbor_roles_uses_fresh_cache_without_regenerating(tmp_path, monkeypatch):
    cache_path = tmp_path / "neighbor_cache.json"
    cache_path.write_text(json.dumps({
        "default": {"generated_at": "2026-07-10",
                    "roles": {"gameplay_engineer": {"terms": {"de": ["x"], "en": ["y"]}}}}
    }), encoding="utf-8")
    called = []
    monkeypatch.setattr(neighbors, "generate_neighbor_roles",
                        lambda profile, core: called.append(1))
    result = neighbors.get_neighbor_roles(_PROFILE, "default", _CORE_ROLES,
                                          today="2026-07-11", cache_path=cache_path)
    assert called == []
    assert result == {"gameplay_engineer": {"terms": {"de": ["x"], "en": ["y"]}}}


def test_get_neighbor_roles_regenerates_when_cache_stale(tmp_path, monkeypatch):
    cache_path = tmp_path / "neighbor_cache.json"
    cache_path.write_text(json.dumps({
        "default": {"generated_at": "2026-07-01", "roles": {"old_role": {"terms": {}}}}
    }), encoding="utf-8")
    monkeypatch.setattr(neighbors, "generate_neighbor_roles",
                        lambda profile, core: {"new_role": {"terms": {"de": ["z"], "en": []}}})
    result = neighbors.get_neighbor_roles(_PROFILE, "default", _CORE_ROLES,
                                          today="2026-07-11", cache_path=cache_path)
    assert result == {"new_role": {"terms": {"de": ["z"], "en": []}}}
