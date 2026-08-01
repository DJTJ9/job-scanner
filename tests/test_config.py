"""Tests für YAML-Configs + Loader."""
import pytest

from jobscanner import config


def test_profile_has_required_sections():
    p = config.load_profile()
    assert "Unity" in p["skills"]
    assert p["level"] == "junior"
    assert "Zeitarbeit/Personaldienstleister" in p["no_gos"]
    assert p["portfolio"] == []


def test_load_profile_reads_named_profile_from_profiles_dir():
    p = config.load_profile("default")
    assert "Unity" in p["skills"]


def test_load_profile_defaults_to_default_profile():
    assert config.load_profile() == config.load_profile("default")


def test_load_profile_missing_name_raises():
    with pytest.raises(FileNotFoundError, match="ghost"):
        config.load_profile("ghost")


def test_queries_cover_three_roles_two_languages():
    q = config.load_queries()
    assert set(q) == {"unity_games", "ai_engineer", "tools_workflow"}
    for role, langs in q.items():
        assert set(langs) == {"de", "en"}
        for lang, terms in langs.items():
            assert 1 <= len(terms) <= 2, f"{role}/{lang}: max 2 Queries (Kosten-Deckel)"


def test_portals_are_the_six_sources():
    portals = config.load_portals()
    names = [p["name"] for p in portals]
    assert names == ["stepstone", "arbeitsagentur", "stellenanzeigen", "indeed",
                     "adzuna", "jooble"]
    for p in portals:
        assert p["site"], p
        assert p["detail_url_pattern"], p


def test_load_portals_rejects_missing_field(tmp_path, monkeypatch):
    bad = tmp_path / "portals.yaml"
    bad.write_text("- name: kaputt\n  site: example.com\n", encoding="utf-8")
    monkeypatch.setattr(config, "_PORTALS_FILE", bad)
    with pytest.raises(ValueError, match="detail_url_pattern"):
        config.load_portals()


def test_html_portals_have_search_url_template():
    portals = config.load_portals()
    for p in portals:
        assert p["search_type"] in ("html", "api", "adzuna", "jooble")
        if p["search_type"] == "html":
            assert "{query}" in p["search_url_template"]


def test_load_portals_rejects_missing_search_type(tmp_path, monkeypatch):
    bad = tmp_path / "portals.yaml"
    bad.write_text(
        "- name: kaputt\n  site: example.com\n  detail_url_pattern: 'x'\n",
        encoding="utf-8")
    monkeypatch.setattr(config, "_PORTALS_FILE", bad)
    with pytest.raises(ValueError, match="search_type"):
        config.load_portals()


class TestHybridPortalConfig:
    def test_fetch_routing_fields(self):
        from jobscanner.config import load_portals
        by_name = {p["name"]: p for p in load_portals()}
        assert by_name["stepstone"]["detail_fetch"] == "firecrawl"
        assert by_name["indeed"]["search_fetch"] == "firecrawl"
        assert by_name["indeed"]["detail_fetch"] == "firecrawl"
        assert by_name["arbeitsagentur"]["firecrawl_failover"] is True
        assert by_name["stellenanzeigen"]["firecrawl_failover"] is True

    def test_aggregator_portals_present(self):
        from jobscanner.config import load_portals
        by_name = {p["name"]: p for p in load_portals()}
        assert by_name["adzuna"]["search_type"] == "adzuna"
        assert by_name["adzuna"]["detail_fetch"] == "api"
        assert by_name["jooble"]["search_type"] == "jooble"
        assert by_name["jooble"]["detail_fetch"] == "api"


def test_firecrawl_budget_default_and_env(monkeypatch):
    monkeypatch.delenv("JOBSCANNER_FC_BUDGET", raising=False)
    assert config.firecrawl_budget() == 100
    monkeypatch.setenv("JOBSCANNER_FC_BUDGET", "42")
    assert config.firecrawl_budget() == 42


def test_load_env_tolerates_unreadable_env_file(monkeypatch):
    """Non-root web-Prozess kann die Bot-.env unter /root (mode 0700) nicht mal
    stat'en → PermissionError. _load_env() muss still überspringen statt zu werfen
    (Vars kommen ohnehin per systemd EnvironmentFile)."""
    class _Unreadable:
        def exists(self):
            raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(config, "_ENV_FILE", _Unreadable())
    config._load_env()  # darf nicht werfen


def test_load_portale_pool_returns_entries_with_meta():
    pool = config.load_portale_pool()
    assert pool, "Pool darf nicht leer sein"
    for p in pool:
        assert p["url"].startswith("https://"), p
        assert p["typ"] in ("portal", "career_page"), p
        assert p["label"], p
        assert p["beschreibung"], p
        assert p.get("firecrawl_needed", False) is False, \
            f"Pool ist Firecrawl-frei: {p['url']}"


def test_load_portale_pool_portal_requires_search_fields(tmp_path, monkeypatch):
    bad = tmp_path / "pool.yaml"
    bad.write_text(
        "- url: 'https://x.de'\n"
        "  typ: portal\n"
        "  label: 'X'\n"
        "  beschreibung: 'Test'\n",
        encoding="utf-8")
    monkeypatch.setattr(config, "_PORTALE_POOL_FILE", bad)
    with pytest.raises(ValueError, match="https://x.de"):
        config.load_portale_pool()


def test_load_portale_pool_career_page_needs_no_search_fields(tmp_path, monkeypatch):
    ok = tmp_path / "pool.yaml"
    ok.write_text(
        "- url: 'https://y.de/jobs'\n"
        "  typ: career_page\n"
        "  label: 'Y'\n"
        "  beschreibung: 'Test'\n",
        encoding="utf-8")
    monkeypatch.setattr(config, "_PORTALE_POOL_FILE", ok)
    assert config.load_portale_pool()[0]["label"] == "Y"


def test_load_portale_pool_missing_label_raises(tmp_path, monkeypatch):
    bad = tmp_path / "pool.yaml"
    bad.write_text(
        "- url: 'https://z.de'\n"
        "  typ: career_page\n"
        "  beschreibung: 'Test'\n",
        encoding="utf-8")
    monkeypatch.setattr(config, "_PORTALE_POOL_FILE", bad)
    with pytest.raises(ValueError, match="label"):
        config.load_portale_pool()
