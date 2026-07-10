"""Tests für YAML-Configs + Loader."""
import pytest

from jobscanner import config


def test_profile_has_required_sections():
    p = config.load_profile()
    assert "Unity" in p["skills"]
    assert p["level"] == "junior"
    assert "Zeitarbeit/Personaldienstleister" in p["no_gos"]
    assert p["portfolio"] == []


def test_queries_cover_three_roles_two_languages():
    q = config.load_queries()
    assert set(q) == {"unity_games", "ai_engineer", "tools_workflow"}
    for role, langs in q.items():
        assert set(langs) == {"de", "en"}
        for lang, terms in langs.items():
            assert 1 <= len(terms) <= 2, f"{role}/{lang}: max 2 Queries (Kosten-Deckel)"


def test_portals_are_the_four_scrapable():
    portals = config.load_portals()
    names = [p["name"] for p in portals]
    assert names == ["stepstone", "arbeitsagentur", "stellenanzeigen", "indeed"]
    for p in portals:
        assert p["site"], p
        assert p["detail_url_pattern"], p


def test_load_portals_rejects_missing_field(tmp_path, monkeypatch):
    bad = tmp_path / "portals.yaml"
    bad.write_text("- name: kaputt\n  site: example.com\n", encoding="utf-8")
    monkeypatch.setattr(config, "_PORTALS_FILE", bad)
    with pytest.raises(ValueError, match="detail_url_pattern"):
        config.load_portals()
