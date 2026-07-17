"""Tests für neighbors.py — Claude-Nachbarrollen-Generierung + Cache mit TTL."""
import json

from jobscanner import neighbors

_PROFILE = {"target_roles": ["Unity/Games Programmer"], "skills": ["Unity", "C#"]}
_CORE_ROLES = {"unity_games", "ai_engineer", "tools_workflow"}

# claude_json gibt die BEREITS GEPARSTE Liste zurück (nicht mehr einen JSON-String)
_NEIGHBOR_LIST = [
    {"name": "gameplay_engineer",
     "terms": {"de": ["Gameplay Programmierer"], "en": ["Gameplay Engineer"]}},
    {"name": "unity_games", "terms": {"de": ["Sollte gefiltert werden"], "en": []}},
]


def test_generate_neighbor_roles_parses_claude_json(monkeypatch):
    monkeypatch.setattr(neighbors, "claude_json",
                        lambda system, prompt: _NEIGHBOR_LIST)
    result = neighbors.generate_neighbor_roles(_PROFILE, _CORE_ROLES)
    assert result["gameplay_engineer"]["terms"]["de"] == ["Gameplay Programmierer"]


def test_generate_neighbor_roles_filters_core_role_collisions(monkeypatch):
    monkeypatch.setattr(neighbors, "claude_json",
                        lambda system, prompt: _NEIGHBOR_LIST)
    result = neighbors.generate_neighbor_roles(_PROFILE, _CORE_ROLES)
    assert "unity_games" not in result


def test_generate_neighbor_roles_returns_empty_on_parse_error(monkeypatch):
    def boom(system, prompt):
        raise ValueError("kein json")
    monkeypatch.setattr(neighbors, "claude_json", boom)
    assert neighbors.generate_neighbor_roles(_PROFILE, _CORE_ROLES) == {}


def test_generate_neighbor_roles_returns_empty_on_call_error(monkeypatch):
    def boom(system, prompt):
        raise RuntimeError("claude down")
    monkeypatch.setattr(neighbors, "claude_json", boom)
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
