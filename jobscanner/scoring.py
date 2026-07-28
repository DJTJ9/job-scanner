"""Matching & Scoring: Regel-Filter (No-Gos) + gewichtete Kriterien-Formel.
Die eigentliche LLM-Bewertung passiert jetzt im Claude-Agent-Batch-Lauf
(llm_batch.py) — dieses Modul liefert nur noch die deterministischen,
LLM-freien Bausteine (Veto-Regex, Gewichtungsformel, Kategorie-Schwellen)."""
from __future__ import annotations

import re

from jobscanner.models import Job

PASS_THRESHOLD = 70
MAYBE_THRESHOLD = 40

_NO_GO_PATTERNS = {
    "Senior-Stelle (5+ Jahre)": re.compile(
        r"\bsenior\b|\b[5-9]\+?\s*jahre\b|\bmehrj[aä]hrige\b", re.IGNORECASE),
    "Zeitarbeit/Personaldienstleister": re.compile(
        r"zeitarbeit|personaldienstleister|arbeitnehmer[uü]berlassung", re.IGNORECASE),
}


def rule_filter(job: Job) -> str | None:
    haystack = " ".join([job.title, job.employment_type, " ".join(job.requirements)])
    for label, pattern in _NO_GO_PATTERNS.items():
        if pattern.search(haystack):
            return label
    return None


# ---------------------------------------------------------------------------
# Deterministischer Member-Scoring-Katalog (LLM-frei, Feld-Regeln)
# ---------------------------------------------------------------------------


def _title_req(job: Job) -> str:
    return " ".join([job.title, *job.requirements]).lower()


def _req(job: Job) -> str:
    return " ".join(job.requirements).lower()


def _emp(job: Job) -> str:
    return (job.employment_type or "").lower()


def _parse_salary(text: str) -> int | None:
    """Größte plausible Jahresgehalt-Zahl aus dem Freitext (k → ×1000)."""
    if not text:
        return None
    vals: list[int] = []
    for digits, suffix in re.findall(r"(\d[\d.\s]*)\s*(k|tsd)?", text.lower()):
        d = digits.replace(".", "").replace(" ", "")
        if not d:
            continue
        v = int(d)
        if suffix in ("k", "tsd"):
            v *= 1000
        if v >= 1000:
            vals.append(v)
    return max(vals) if vals else None


_TREND_TECH = {"rust", "ai", "llm", "kubernetes", "typescript", "go", "react", "kafka", "pytorch"}


def _r_remote(job, p):
    return {"remote": (10, "voll remote"), "hybrid": (6, "hybrid"),
            "onsite": (0, "vor Ort")}.get(job.remote_flag)


def _r_junior(job, p):
    t = _title_req(job)
    if re.search(r"junior|entry|berufseinsteiger|absolvent", t):
        return (10, "Junior/Entry")
    if re.search(r"senior|lead|\b[5-9]\+?\s*jahre", t):
        return (0, "Senior-Signal")
    return (5, "kein Level-Signal")


def _r_tech(job, p):
    skills = {s.lower() for s in p.get("skills", [])}
    stack = {s.lower() for s in job.tech_stack}
    if not skills or not stack:
        return None
    inter, union = skills & stack, skills | stack
    return (round(len(inter) / len(union) * 10), f"{len(inter)} Tech-Überschneidungen")


def _r_fest(job, p):
    e = _emp(job)
    if not e:
        return None
    if re.search(r"fest|unbefristet|permanent", e):
        return (10, "Festanstellung")
    if re.search(r"befristet", e):
        return (3, "befristet")
    return None


def _r_teilzeit(job, p):
    t = _emp(job) + " " + job.title.lower()
    return (10, "Teilzeit") if re.search(r"teilzeit|part-time", t) else (0, "keine Teilzeit")


def _r_vollzeit(job, p):
    return (10, "Vollzeit") if re.search(r"vollzeit|full-time", _emp(job)) else None


def _r_gehalt_genannt(job, p):
    return (10, "Gehalt genannt") if job.salary_text.strip() else (0, "kein Gehalt")


def _r_standort(job, p):
    if not job.location:
        return None
    cities = [c.strip().lower() for c in (p.get("cities") or []) if c.strip()]
    if not cities:
        legacy = (p.get("location") or "").strip().lower()
        cities = [legacy] if legacy else []
    if not cities:
        return None
    loc = job.location.lower()
    return (10, "Standort passt") if any(c in loc for c in cities) else (0, "anderer Ort")


def _r_sprache(job, p):
    if not job.language:
        return None
    langs = [l.lower() for l in p.get("languages", [])]
    return (10, "Sprache passt") if job.language.lower() in langs else (3, "andere Sprache")


def _r_domaene(job, p):
    keys = set(p.get("domains", []))
    patterns = [d["pattern"] for d in DOMAINS_CATALOG if d["key"] in keys]
    if not patterns:
        return None
    rx = re.compile("|".join(patterns), re.I)
    return (10, "Domäne passt") if rx.search(_title_req(job)) else (0, "andere Domäne")


def _r_unbefristet(job, p):
    t = _emp(job) + " " + _req(job)
    if re.search(r"unbefristet", t):
        return (10, "unbefristet")
    if re.search(r"befristet", t):
        return (0, "befristet")
    return None


def _r_weiterbildung(job, p):
    return (10, "Weiterbildung genannt") if re.search(
        r"weiterbildung|fortbildung|schulung|mentoring", _req(job)) else (0, "keine")


def _r_flex(job, p):
    return (10, "flexible Zeiten") if re.search(
        r"gleitzeit|flexible arbeitszeit|vertrauensarbeitszeit", _title_req(job)) else (0, "keine")


def _r_startup(job, p):
    t = job.title.lower() + " " + job.company.lower() + " " + _req(job)
    return (10, "Startup") if re.search(r"start-?up", t) else (0, "kein Startup")


def _r_konzern(job, p):
    t = job.title.lower() + " " + job.company.lower() + " " + _req(job)
    return (10, "etabliert") if re.search(r"konzern|gmbh & co|\bag\b|enterprise", t) else (0, "kein Konzern")


def _r_homeoffice(job, p):
    return {"remote": (10, "voll remote"), "hybrid": (6, "hybrid")}.get(
        job.remote_flag, (0, "wenig Home-Office"))


def _r_keine_reise(job, p):
    return (0, "Reise nötig") if re.search(
        r"reisebereitschaft|travel 50|außendienst", _req(job)) else (10, "wenig Reise")


def _r_quereinstieg(job, p):
    return (10, "Quereinstieg ok") if re.search(
        r"quereinstieg|quereinsteiger|auch ohne abschluss", _title_req(job)) else (5, "kein Signal")


def _r_team(job, p):
    return (8, "Kultur betont") if re.search(r"team|kultur|miteinander|duz", _req(job)) else (4, "wenig Kultur")


def _r_moderne_tech(job, p):
    stack = {s.lower() for s in job.tech_stack}
    if not stack:
        return None
    hits = stack & _TREND_TECH
    return (min(10, len(hits) * 4), f"{len(hits)} moderne Technologien")


def _r_gehalt_hoch(job, p):
    n = _parse_salary(job.salary_text)
    if n is None:
        return None
    if n >= 60000:
        return (10, "hohes Gehalt")
    if n >= 45000:
        return (6, "mittleres Gehalt")
    return (2, "niedriges Gehalt")


def _r_branche(job, p):
    t = job.title.lower() + " " + job.company.lower()
    return (10, "IT/Software") if re.search(r"software|\bit\b|tech|entwicklung", t) else (3, "andere Branche")


def _r_benefits(job, p):
    return (8, "Benefits genannt") if re.search(
        r"benefits|jobrad|urban sports|zuschuss", _req(job)) else (4, "wenig Benefits")


def _r_sofort(job, p):
    return (8, "baldiger Start") if re.search(
        r"ab sofort|zeitnah|nächstmöglich", _req(job)) else (5, "kein Signal")


def _r_international(job, p):
    return (8, "international") if re.search(
        r"international|englischsprachig|english-speaking", _title_req(job)) else (4, "kein Signal")


SKILL_SUGGESTIONS = [
    "C++", "C#", "Unity", "Unreal", "Godot", "Gameplay", "Rendering/Graphics",
    "Shader/HLSL", "Physics", "Multiplayer/Netcode", "AI/NPC", "Vulkan", "DirectX",
    "Tools Programming", "ECS",
    "Python", "TypeScript", "React", "Node.js", "Go", "Rust", "Java", "Kotlin",
    "SQL", "Git", "Docker", "Kubernetes", "CI/CD", "AWS", "REST",
]

ROLE_SUGGESTIONS = [
    "Gameplay Programmer", "Engine Programmer", "Graphics Programmer",
    "Tools Programmer", "AI Programmer", "Network Programmer", "Technical Artist",
    "Technical Game Designer", "Game Designer", "Junior Game Programmer",
    "Software Engineer", "Backend Engineer", "Frontend Engineer", "Full-Stack Engineer",
    "DevOps Engineer", "Mobile Developer", "Data Engineer", "ML Engineer",
    "QA Engineer", "SRE", "Junior Developer", "Werkstudent Software-Development",
]

DOMAINS_CATALOG = [
    {"key": "games", "label": "Games allgemein", "pattern": r"game[s]?|spiele|gaming"},
    {"key": "serious_games", "label": "Serious Games", "pattern": r"serious game"},
    {"key": "mobile_games", "label": "Mobile Games", "pattern": r"mobile game"},
    {"key": "aaa_konsole", "label": "AAA/Konsole", "pattern": r"\baaa\b|konsole|console|playstation|xbox"},
    {"key": "indie", "label": "Indie", "pattern": r"\bindie\b"},
    {"key": "xr", "label": "XR/AR/VR", "pattern": r"\bxr\b|\bar\b|\bvr\b|augmented|virtual reality"},
    {"key": "film_vfx", "label": "Film/VFX/Animation", "pattern": r"vfx|animation|\bfilm\b"},
    {"key": "igaming", "label": "iGaming/Glücksspiel", "pattern": r"igaming|glücksspiel|casino|betting|\bwett"},
    {"key": "sport", "label": "Sport", "pattern": r"\bsport\b"},
    {"key": "edtech", "label": "EdTech/E-Learning", "pattern": r"edtech|e-?learning|bildung"},
    {"key": "simulation", "label": "Simulation", "pattern": r"simulation|simulator"},
    {"key": "health", "label": "Health/MedTech", "pattern": r"health|gesundheit|medtech|medizin"},
    {"key": "automotive", "label": "Automotive", "pattern": r"automotive|automobil|fahrzeug"},
    {"key": "robotik_iot", "label": "Robotik/IoT", "pattern": r"robot|\biot\b|embedded"},
    {"key": "fintech", "label": "Fintech", "pattern": r"fintech|banking|finanz"},
    {"key": "ecommerce", "label": "E-Commerce", "pattern": r"e-?commerce|online-?shop"},
    {"key": "saas", "label": "SaaS/B2B", "pattern": r"\bsaas\b|\bb2b\b"},
    {"key": "ki_ml", "label": "KI/Machine Learning", "pattern": r"\bki\b|\bai\b|machine learning|\bml\b|künstliche intelligenz"},
    {"key": "cybersecurity", "label": "Cybersecurity", "pattern": r"cyber|security|it-sicherheit"},
    {"key": "govtech", "label": "GovTech", "pattern": r"govtech|öffentlicher dienst|behörde|verwaltung"},
    {"key": "logistik", "label": "Logistik", "pattern": r"logistik|logistics|supply chain"},
]

CITY_SUGGESTIONS = ["Berlin", "Hamburg", "München", "Köln", "Frankfurt",
                    "Stuttgart", "Düsseldorf", "Leipzig", "Remote"]

EMPLOYMENT_OPTIONS = ["Vollzeit", "Teilzeit", "Werkstudent", "Praktikum",
                      "Freelance/Werkvertrag", "Ausbildung", "Duales Studium", "Minijob"]

LANGUAGE_OPTIONS = [
    {"code": "de", "label": "Deutsch"}, {"code": "en", "label": "Englisch"},
    {"code": "fr", "label": "Französisch"}, {"code": "es", "label": "Spanisch"},
    {"code": "it", "label": "Italienisch"}, {"code": "nl", "label": "Niederländisch"},
    {"code": "pl", "label": "Polnisch"}, {"code": "pt", "label": "Portugiesisch"},
    {"code": "ru", "label": "Russisch"}, {"code": "tr", "label": "Türkisch"},
]

WEIGHTS_CATALOG = [
    {"key": "remote", "label": "Remote möglich", "default_weight": 4, "rule": _r_remote},
    {"key": "junior_level", "label": "Junior/Entry-Level", "default_weight": 5, "rule": _r_junior},
    {"key": "tech_stack_match", "label": "Tech-Stack passt", "default_weight": 4, "rule": _r_tech},
    {"key": "festanstellung", "label": "Festanstellung", "default_weight": 3, "rule": _r_fest},
    {"key": "teilzeit", "label": "Teilzeit möglich", "default_weight": 0, "rule": _r_teilzeit},
    {"key": "vollzeit", "label": "Vollzeit", "default_weight": 2, "rule": _r_vollzeit},
    {"key": "gehalt_genannt", "label": "Gehalt genannt", "default_weight": 2, "rule": _r_gehalt_genannt},
    {"key": "standort", "label": "Standort-Präferenz", "default_weight": 3, "rule": _r_standort},
    {"key": "sprache", "label": "Sprache passt", "default_weight": 2, "rule": _r_sprache},
    {"key": "domaene", "label": "Domänen-Bonus", "default_weight": 3, "rule": _r_domaene},
    {"key": "unbefristet", "label": "Unbefristet", "default_weight": 2, "rule": _r_unbefristet},
    {"key": "weiterbildung", "label": "Weiterbildung genannt", "default_weight": 2, "rule": _r_weiterbildung},
    {"key": "flex_zeit", "label": "Flexible Arbeitszeiten", "default_weight": 2, "rule": _r_flex},
    {"key": "startup", "label": "Startup-Umfeld", "default_weight": 0, "rule": _r_startup},
    {"key": "grosses_unternehmen", "label": "Etabliertes Unternehmen", "default_weight": 0, "rule": _r_konzern},
    {"key": "homeoffice_anteil", "label": "Home-Office-Anteil hoch", "default_weight": 3, "rule": _r_homeoffice},
    {"key": "keine_reise", "label": "Wenig Reisetätigkeit", "default_weight": 2, "rule": _r_keine_reise},
    {"key": "quereinstieg", "label": "Quereinstieg willkommen", "default_weight": 2, "rule": _r_quereinstieg},
    {"key": "team_kultur", "label": "Team-/Kultur-Betonung", "default_weight": 2, "rule": _r_team},
    {"key": "moderne_tech", "label": "Moderne Technologien", "default_weight": 3, "rule": _r_moderne_tech},
    {"key": "gehalt_hoch", "label": "Gehalt hoch", "default_weight": 2, "rule": _r_gehalt_hoch},
    {"key": "branche_it", "label": "IT/Software-Branche", "default_weight": 3, "rule": _r_branche},
    {"key": "benefits", "label": "Benefits genannt", "default_weight": 2, "rule": _r_benefits},
    {"key": "sofort_start", "label": "Baldiger Start", "default_weight": 1, "rule": _r_sofort},
    {"key": "internationales_team", "label": "Internationales Umfeld", "default_weight": 2, "rule": _r_international},
]

_WEIGHT_RULES = {w["key"]: w["rule"] for w in WEIGHTS_CATALOG}


def _v_senior(job, p):
    return bool(re.search(r"\bsenior\b|\blead\b|\b[5-9]\+?\s*jahre|mehrj[aä]hrige", _title_req(job)))


def _v_zeitarbeit(job, p):
    return bool(re.search(r"zeitarbeit|personaldienstleister|arbeitnehmer[uü]berlassung", _title_req(job)))


def _v_onsite(job, p):
    return job.remote_flag == "onsite"


def _v_reise(job, p):
    return bool(re.search(r"reisebereitschaft.{0,12}(5\d|[6-9]\d)|außendienst", _req(job)))


def _v_unbezahlt(job, p):
    t = _title_req(job)
    return "praktikum" in t and bool(re.search(r"unbezahlt|ohne vergütung", t))


def _v_nacht(job, p):
    return bool(re.search(r"nachtschicht|schichtdienst", _req(job)))


def _v_vertrieb(job, p):
    return bool(re.search(r"vertrieb|\bsales\b|außendienst", job.title.lower()))


def _v_fuehrung(job, p):
    return bool(re.search(r"teamleitung|führungserfahrung erforderlich|führungskraft", _title_req(job)))


def _v_befristet(job, p):
    t = _emp(job) + " " + _req(job)
    return bool(re.search(r"befristet|zeitlich begrenzt", t)) and not re.search(r"unbefristet", t)


def _v_oncall(job, p):
    return bool(re.search(r"rufbereitschaft|on-call", _req(job)))


def _v_umzug(job, p):
    return bool(re.search(r"umzug erforderlich|relocation required", _req(job)))


def _v_agentur(job, p):
    return bool(re.search(r"werbeagentur|personalvermittlung", job.company.lower() + " " + _req(job)))


def _v_werkstudent(job, p):
    return bool(re.search(r"werkstudent", _emp(job) + " " + job.title.lower()))


def _v_wochenende(job, p):
    return bool(re.search(r"wochenendarbeit|wochenenddienst", _req(job)))


def _v_sprache(job, p):
    if not job.language:
        return False
    langs = [l.lower() for l in p.get("languages", [])]
    return bool(langs) and job.language.lower() not in langs


def _v_crunch(job, p):
    return bool(re.search(r"crunch|unbezahlte überstunden|überstunden.{0,15}unbezahlt", _title_req(job)))


def _v_igaming(job, p):
    return bool(re.search(r"igaming|glücksspiel|casino|betting|\bwett", _title_req(job) + " " + job.company.lower()))


def _v_f2p(job, p):
    return bool(re.search(r"free-?to-?play|free2play|\bf2p\b|micro-?transaction|in-app-käufe", _title_req(job)))


def _v_qa_only(job, p):
    t = job.title.lower()
    if re.search(r"develop|entwickl|programmer", t):
        return False
    return bool(re.search(r"\bqa\b|quality assurance|test engineer|\btester\b|game tester|test automation", t))


def _v_outsourcing(job, p):
    return bool(re.search(r"outsourcing|game publisher|publishing-agentur", _title_req(job) + " " + job.company.lower()))


def _v_praesenz5(job, p):
    return bool(re.search(r"präsenzpflicht|5 tage.{0,12}(büro|vor ort)|vollständig vor ort", _req(job)))


def _v_reloc_ausland(job, p):
    return bool(re.search(r"relocation.{0,20}(ausland|abroad)|umzug ins ausland|relocate abroad", _req(job)))


def _v_provision(job, p):
    return bool(re.search(r"provision|kommission|commission-based|erfolgsbasierte vergütung", _title_req(job)))


def _v_kaltakquise(job, p):
    return bool(re.search(r"kaltakquise|cold[- ]calling|neukundenakquise", _title_req(job)))


def _v_legacy_only(job, p):
    return bool(re.search(r"legacy-system|reine wartung|wartungsprojekt|legacy-codebasis|bestandspflege", _title_req(job)))


NO_GOS_CATALOG = [
    {"key": "senior_5j", "label": "Senior (5+ Jahre)", "veto": _v_senior},
    {"key": "zeitarbeit", "label": "Zeitarbeit", "veto": _v_zeitarbeit},
    {"key": "nur_onsite", "label": "Nur vor Ort", "veto": _v_onsite},
    {"key": "viel_reise", "label": "Viel Reise", "veto": _v_reise},
    {"key": "unbezahltes_praktikum", "label": "Unbezahltes Praktikum", "veto": _v_unbezahlt},
    {"key": "nachtschicht", "label": "Nacht-/Schichtdienst", "veto": _v_nacht},
    {"key": "vertrieb", "label": "Vertrieb/Sales", "veto": _v_vertrieb},
    {"key": "fuehrungsrolle", "label": "Führungsrolle", "veto": _v_fuehrung},
    {"key": "befristet", "label": "Befristet", "veto": _v_befristet},
    {"key": "on_call", "label": "Rufbereitschaft", "veto": _v_oncall},
    {"key": "umzug_pflicht", "label": "Umzug erforderlich", "veto": _v_umzug},
    {"key": "agentur", "label": "Agentur/Vermittlung", "veto": _v_agentur},
    {"key": "werkstudent", "label": "Werkstudent", "veto": _v_werkstudent},
    {"key": "wochenende", "label": "Wochenendarbeit", "veto": _v_wochenende},
    {"key": "unpassende_sprache", "label": "Unpassende Sprache", "veto": _v_sprache},
    {"key": "crunch", "label": "Crunch/unbezahlte Überstunden", "veto": _v_crunch},
    {"key": "igaming", "label": "iGaming/Glücksspiel", "veto": _v_igaming},
    {"key": "free_to_play", "label": "Free-to-Play/Monetarisierung", "veto": _v_f2p},
    {"key": "qa_only", "label": "Reine QA-/Test-Rolle", "veto": _v_qa_only},
    {"key": "outsourcing", "label": "Outsourcing/Publisher-Agentur", "veto": _v_outsourcing},
    {"key": "praesenz_5tage", "label": "Präsenzpflicht 5 Tage/Woche", "veto": _v_praesenz5},
    {"key": "relocation_ausland", "label": "Relocation ins Ausland Pflicht", "veto": _v_reloc_ausland},
    {"key": "provision", "label": "Provisionsbasierte Vergütung", "veto": _v_provision},
    {"key": "kaltakquise", "label": "Kaltakquise", "veto": _v_kaltakquise},
    {"key": "legacy_only", "label": "Reine Legacy-/Wartungs-Codebasis", "veto": _v_legacy_only},
]


def score_job_deterministic(job: Job, criteria: list[dict], active_no_gos: list[str],
                            profile_data: dict) -> tuple[int | None, dict, str | None, str]:
    """LLM-freier Score aus Katalog-Regeln. Erster aktiver Veto-Treffer → (0, {}, 'No-Go', label).
    Sonst: breakdown wie beim LLM ({key: {punkte, grund}}) → gewichtete Summe wiederverwenden."""
    active = set(active_no_gos)
    for n in NO_GOS_CATALOG:
        if n["key"] in active and n["veto"](job, profile_data):
            return 0, {}, "No-Go", n["label"]
    breakdown: dict = {}
    for crit in criteria:
        if crit["weight"] <= 0:
            continue
        rule = _WEIGHT_RULES.get(crit["key"])
        if rule is None:
            continue
        res = rule(job, profile_data)
        if res is None:
            continue
        punkte, grund = res
        breakdown[crit["key"]] = {"punkte": punkte, "grund": grund}
    score = compute_weighted_score(breakdown, criteria)
    category = category_for_score(score) if score is not None else None
    reason = top_reasons(breakdown, criteria) if breakdown else "nicht bewertbar"
    return score, breakdown, category, reason


def category_for_score(score: int) -> str:
    if score >= PASS_THRESHOLD:
        return "Pass"
    if score >= MAYBE_THRESHOLD:
        return "Vielleicht"
    return "No-Go"


def compute_weighted_score(breakdown: dict, criteria: list[dict]) -> int | None:
    """Normalisierte gewichtete Summe: Σ(p×w)/Σ(10×w)×100 über bewertbare Kriterien."""
    numerator = 0
    denominator = 0
    for crit in criteria:
        if crit["weight"] <= 0:
            continue
        entry = breakdown.get(crit["key"])
        if entry is None or entry.get("punkte") is None:
            continue
        punkte = max(0, min(10, int(entry["punkte"])))
        numerator += punkte * crit["weight"]
        denominator += 10 * crit["weight"]
    if denominator == 0:
        return None
    return round(numerator / denominator * 100)


def top_reasons(breakdown: dict, criteria: list[dict], n: int = 2) -> str:
    """Formatiert die Top-n bewerteten Kriterien als Kurzbegründung."""
    top = sorted(
        ((c["key"], breakdown.get(c["key"], {})) for c in criteria
         if breakdown.get(c["key"], {}).get("punkte") is not None),
        key=lambda kv: kv[1]["punkte"], reverse=True)[:n]
    return "; ".join(f"{k}: {v.get('grund', '')}" for k, v in top) or "bewertet"
