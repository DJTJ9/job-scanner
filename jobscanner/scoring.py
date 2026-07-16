"""Matching & Scoring: Regel-Filter (No-Gos) + gewichtete Kriterien-Formel.
Die eigentliche LLM-Bewertung passiert jetzt im Claude-Agent-Batch-Lauf
(llm_batch.py) — dieses Modul liefert nur noch die deterministischen,
Groq-freien Bausteine (Veto-Regex, Gewichtungsformel, Kategorie-Schwellen)."""
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


_DOMAIN_RE = re.compile(r"sport|edtech|serious game|simulation|\bxr\b|health|gesundheit", re.I)
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
    loc = (p.get("location") or "").strip().lower()
    if not job.location or not loc:
        return None
    return (10, "Standort passt") if loc in job.location.lower() else (0, "anderer Ort")


def _r_sprache(job, p):
    if not job.language:
        return None
    langs = [l.lower() for l in p.get("languages", [])]
    return (10, "Sprache passt") if job.language.lower() in langs else (3, "andere Sprache")


def _r_domaene(job, p):
    return (10, "Domäne passt") if _DOMAIN_RE.search(_title_req(job)) else (0, "andere Domäne")


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
]


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
