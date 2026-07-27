"""Job-Datenmodell und Fingerprint-Normalisierung (Dedup-Vorbereitung 1.4)."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"[^a-z0-9äöüß]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


_LEGAL_SUFFIX_RE = re.compile(r"\s+(gmbh co kg|gmbh|mbh|ug|ag|kg|ohg|gbr|e v|ev)$")


def _strip_legal_suffix(text: str) -> str:
    stripped = _LEGAL_SUFFIX_RE.sub("", text)
    return stripped if stripped else text


def make_fingerprint(company: str, title: str, location: str) -> str:
    company_norm = _strip_legal_suffix(_norm(company or ""))
    return "|".join([company_norm, _norm(title or ""), _norm(location or "")])


_ABBREV = {"sr": "senior", "jr": "junior"}
_GENDER_TOKENS = {"m", "w", "d", "f", "x", "gn"}
_COUNTRY_TOKENS = {"deutschland", "germany", "de", "österreich", "austria", "schweiz"}
_PLACE_QUALIFIERS = {"remote", "hybrid", "onsite", "homeoffice"}
_PLZ_RE = re.compile(r"^\d{4,5}$")


def _canonical_title(title: str) -> str:
    out = []
    for tok in _norm(title or "").split():
        if tok in _GENDER_TOKENS:
            continue
        out.append(_ABBREV.get(tok, tok))
    return " ".join(out)


def _city_token(location: str) -> str:
    for tok in _norm(location or "").split():
        if tok in _COUNTRY_TOKENS or tok in _PLACE_QUALIFIERS or _PLZ_RE.match(tok):
            continue
        return tok
    return ""


def match_key(company: str, title: str, location: str) -> str:
    company_norm = _strip_legal_suffix(_norm(company or ""))
    return "|".join([company_norm, _canonical_title(title), _city_token(location)])


@dataclass
class Job:
    title: str
    company: str
    location: str = ""
    remote_flag: str = "unknown"        # onsite/hybrid/remote/unknown
    employment_type: str = ""
    language: str = ""                  # de/en
    salary_text: str = ""
    requirements: list = field(default_factory=list)
    tech_stack: list = field(default_factory=list)
    role: str = ""                      # Zielrolle aus queries.yaml (z.B. "unity_games")
    is_neighbor: bool = False           # True: Job über Claude-generierte Nachbarrolle gefunden
    sources: list = field(default_factory=list)  # [{portal, url, found_at}]
    first_seen: str = ""                # ISO YYYY-MM-DD
    last_seen: str = ""
    archive_path: str | None = None
    score: int | None = None
    score_reason: str | None = None
    category: str | None = None
    status: str = "neu"                 # neu/interessant/beworben/interview/abgelehnt
    nocodb_row_id: int | None = None

    @property
    def fingerprint(self) -> str:
        return make_fingerprint(self.company, self.title, self.location)
