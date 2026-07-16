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
