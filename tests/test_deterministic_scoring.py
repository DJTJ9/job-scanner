"""Tests für den deterministischen (LLM-freien) Member-Scoring-Pfad."""
import jobscanner.scoring as scoring
from jobscanner.models import Job


def _job(**overrides) -> Job:
    base = dict(title="Junior Unity Developer", company="ACME GmbH", location="Hamburg",
                remote_flag="remote", employment_type="Festanstellung, Vollzeit",
                language="de", salary_text="55.000 € brutto",
                requirements=["Unity", "C#", "Weiterbildung möglich"],
                tech_stack=["Unity", "C#"])
    base.update(overrides)
    return Job(**base)


_P = {"skills": ["Unity", "C#", "Python"], "languages": ["de"], "location": "Hamburg"}


def _rule(key):
    return {w["key"]: w["rule"] for w in scoring.WEIGHTS_CATALOG}[key]


def test_catalog_sizes():
    assert len(scoring.WEIGHTS_CATALOG) >= 25
    assert len(scoring.NO_GOS_CATALOG) >= 15
    assert all({"key", "label", "default_weight", "rule"} <= set(w) for w in scoring.WEIGHTS_CATALOG)
    assert all({"key", "label", "veto"} <= set(n) for n in scoring.NO_GOS_CATALOG)


def test_remote_rule_maps_flag_to_points():
    assert _rule("remote")(_job(remote_flag="remote"), _P) == (10, "voll remote")
    assert _rule("remote")(_job(remote_flag="hybrid"), _P)[0] == 6
    assert _rule("remote")(_job(remote_flag="onsite"), _P)[0] == 0
    assert _rule("remote")(_job(remote_flag="unknown"), _P) is None


def test_junior_rule():
    assert _rule("junior_level")(_job(title="Junior Developer"), _P)[0] == 10
    assert _rule("junior_level")(_job(title="Senior Developer", requirements=["5 Jahre"]), _P)[0] == 0
    assert _rule("junior_level")(_job(title="Developer", requirements=["Team"]), _P)[0] == 5


def test_tech_stack_jaccard():
    p, g = _rule("tech_stack_match")(_job(tech_stack=["Unity", "C#"]), _P)
    # {unity,c#} ∩ {unity,c#,python} = 2 ; union = 3 ; round(2/3*10)=7
    assert p == 7
    assert _rule("tech_stack_match")(_job(tech_stack=[]), _P) is None


def test_gehalt_genannt_rule():
    assert _rule("gehalt_genannt")(_job(salary_text="55.000 €"), _P)[0] == 10
    assert _rule("gehalt_genannt")(_job(salary_text=""), _P)[0] == 0


def test_festanstellung_unbefristet_not_matched_as_befristet():
    # "unbefristet" darf nicht als "befristet" (3) fehlklassifiziert werden
    assert _rule("festanstellung")(_job(employment_type="unbefristet"), _P)[0] == 10
    assert _rule("festanstellung")(_job(employment_type="befristet"), _P)[0] == 3
    assert _rule("festanstellung")(_job(employment_type=""), _P) is None


def test_no_go_senior_veto():
    veto = {n["key"]: n["veto"] for n in scoring.NO_GOS_CATALOG}["senior_5j"]
    assert veto(_job(title="Senior Developer"), _P) is True
    assert veto(_job(title="Junior Developer"), _P) is False


def test_no_go_onsite_veto():
    veto = {n["key"]: n["veto"] for n in scoring.NO_GOS_CATALOG}["nur_onsite"]
    assert veto(_job(remote_flag="onsite"), _P) is True
    assert veto(_job(remote_flag="remote"), _P) is False


def test_no_go_language_veto_uses_profile():
    veto = {n["key"]: n["veto"] for n in scoring.NO_GOS_CATALOG}["unpassende_sprache"]
    assert veto(_job(language="fr"), {"languages": ["de", "en"]}) is True
    assert veto(_job(language="de"), {"languages": ["de", "en"]}) is False


def test_score_job_veto_returns_zero_no_go():
    job = _job(title="Senior Developer")
    score, breakdown, category, reason = scoring.score_job_deterministic(
        job, [{"key": "remote", "label": "Remote", "weight": 5}],
        active_no_gos=["senior_5j"], profile_data=_P)
    assert score == 0
    assert breakdown == {}
    assert category == "No-Go"
    assert reason == "Senior (5+ Jahre)"


def test_score_job_weighted_sum_from_rules():
    job = _job(remote_flag="remote", salary_text="")   # remote=10, gehalt_genannt=0
    criteria = [{"key": "remote", "label": "Remote", "weight": 5},
                {"key": "gehalt_genannt", "label": "Gehalt", "weight": 5}]
    score, breakdown, category, reason = scoring.score_job_deterministic(
        job, criteria, active_no_gos=[], profile_data=_P)
    # (10*5 + 0*5) / (10*10) * 100 = 50
    assert score == 50
    assert breakdown["remote"]["punkte"] == 10
    assert breakdown["gehalt_genannt"]["punkte"] == 0
    assert category == "Vielleicht"


def test_score_job_rule_none_excluded_from_breakdown():
    job = _job(remote_flag="unknown")   # _r_remote → None
    score, breakdown, category, reason = scoring.score_job_deterministic(
        job, [{"key": "remote", "label": "Remote", "weight": 5},
              {"key": "gehalt_genannt", "label": "Gehalt", "weight": 5}],
        active_no_gos=[], profile_data=_P)
    assert "remote" not in breakdown
    assert "gehalt_genannt" in breakdown


def test_score_job_inactive_no_go_key_ignored():
    # senior_5j NICHT in active_no_gos → kein Veto trotz Senior-Titel
    job = _job(title="Senior Developer", remote_flag="remote")
    score, breakdown, category, reason = scoring.score_job_deterministic(
        job, [{"key": "remote", "label": "Remote", "weight": 5}],
        active_no_gos=["zeitarbeit"], profile_data=_P)
    assert category != "No-Go"
    assert score == 100


def test_domains_and_preset_catalogs_present():
    assert len(scoring.DOMAINS_CATALOG) >= 20
    assert all({"key", "label", "pattern"} <= set(d) for d in scoring.DOMAINS_CATALOG)
    assert {"games", "sport", "fintech"} <= {d["key"] for d in scoring.DOMAINS_CATALOG}
    assert len(scoring.SKILL_SUGGESTIONS) >= 25 and "Unity" in scoring.SKILL_SUGGESTIONS
    assert len(scoring.ROLE_SUGGESTIONS) >= 20
    assert scoring.CITY_SUGGESTIONS[0] == "Berlin" and "Remote" in scoring.CITY_SUGGESTIONS
    assert "Vollzeit" in scoring.EMPLOYMENT_OPTIONS
    assert {"code": "de", "label": "Deutsch"} in scoring.LANGUAGE_OPTIONS


def test_r_domaene_personalized_by_profile_domains():
    rule = _rule("domaene")
    sport_job = _job(title="Sport Data Engineer", requirements=["Analytics"])
    games_job = _job(title="Gameplay Programmer", requirements=["Unity"])
    assert rule(sport_job, {"domains": []}) is None      # leer → nicht bewertbar
    assert rule(games_job, {}) is None
    assert rule(sport_job, {"domains": ["sport"]}) == (10, "Domäne passt")
    assert rule(games_job, {"domains": ["sport"]}) == (0, "andere Domäne")
    assert rule(games_job, {"domains": ["games", "sport"]})[0] == 10


def test_r_standort_multi_city_and_legacy_fallback():
    rule = _rule("standort")
    job = _job(location="Hamburg, hybrid")
    assert rule(job, {"cities": ["Berlin", "Hamburg"]}) == (10, "Standort passt")
    assert rule(job, {"cities": ["Berlin", "München"]}) == (0, "anderer Ort")
    assert rule(job, {"location": "hamburg"})[0] == 10   # Legacy-Fallback
    assert rule(job, {}) is None
    assert rule(_job(location=""), {"cities": ["Hamburg"]}) is None


def test_new_no_go_vetos_present_and_fire():
    vetos = {n["key"]: n["veto"] for n in scoring.NO_GOS_CATALOG}
    new_keys = {"crunch", "igaming", "free_to_play", "qa_only", "outsourcing",
                "praesenz_5tage", "relocation_ausland", "provision", "kaltakquise",
                "legacy_only"}
    assert new_keys <= set(vetos)
    assert vetos["igaming"](_job(title="Backend Dev", company="LuckyCasino GmbH"), _P) is True
    assert vetos["crunch"](_job(requirements=["Crunch-Phasen üblich"]), _P) is True
    assert vetos["free_to_play"](_job(title="F2P Monetization Designer"), _P) is True
    assert vetos["qa_only"](_job(title="Game Tester"), _P) is True
    assert vetos["qa_only"](_job(title="Software Developer"), _P) is False
    assert vetos["kaltakquise"](_job(title="Sales", requirements=["Kaltakquise"]), _P) is True
    assert vetos["legacy_only"](_job(requirements=["Reine Wartung der Legacy-Codebasis"]), _P) is True
    # unbeteiligter Dev-Job löst KEINEN neuen Veto aus
    clean = _job(title="Junior Unity Developer", company="ACME GmbH", requirements=["Unity"])
    for k in new_keys:
        assert vetos[k](clean, _P) is False


import pytest
from jobscanner import storage


@pytest.fixture
def db(tmp_path):
    storage.init_db(tmp_path / "jobs.db")
    yield
    storage.close()


def _extracted(**kw):
    """upsert_job setzt extraction_status default 'extracted'."""
    return storage.upsert_job(_job(**kw))


def test_score_profile_scores_whole_pool_without_llm(db):
    fp1 = _extracted(title="Junior Unity Developer", company="A GmbH", remote_flag="remote")
    fp2 = _extracted(title="Senior Architect", company="B GmbH", remote_flag="onsite",
                     requirements=["5 Jahre Erfahrung"])
    pid = storage.create_profile(
        "Member", {"skills": ["Unity"], "languages": ["de"], "location": "Hamburg",
                   "no_gos": ["senior_5j"]})
    storage.save_criteria(pid, [
        {"key": "remote", "label": "Remote", "weight": 5, "sort": 0},
        {"key": "junior_level", "label": "Junior", "weight": 5, "sort": 1},
    ])
    n = storage.score_profile_deterministic(pid)
    assert n == 2
    s1 = storage.get_job_score(pid, fp1)
    assert s1["score"] > 0 and s1["category"] != "No-Go"
    s2 = storage.get_job_score(pid, fp2)
    assert s2["score"] == 0 and s2["category"] == "No-Go"


def test_score_profile_recompute_on_weight_change_without_prior_breakdown(db):
    fp = _extracted(title="Junior Unity Developer", company="A GmbH", remote_flag="hybrid")
    pid = storage.create_profile("Member", {"skills": ["Unity"], "languages": ["de"], "no_gos": []})
    storage.save_criteria(pid, [{"key": "remote", "label": "Remote", "weight": 5, "sort": 0}])
    storage.score_profile_deterministic(pid)
    first = storage.get_job_score(pid, fp)["score"]        # remote=hybrid → 6 → 60
    # Gewicht ändern + neu bewerten (Feintuning-Analog, KEIN vorhandenes LLM-breakdown nötig)
    storage.save_criteria(pid, [
        {"key": "remote", "label": "Remote", "weight": 5, "sort": 0},
        {"key": "junior_level", "label": "Junior", "weight": 5, "sort": 1},
    ])
    storage.score_profile_deterministic(pid)
    second = storage.get_job_score(pid, fp)["score"]       # +junior=10 → (6*5+10*5)/100*100=80
    assert first == 60 and second == 80
