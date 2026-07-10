"""Job-Datenmodell und Fingerprint-Normalisierung (Dedup-Vorbereitung 1.4)."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"[^a-z0-9äöüß]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def make_fingerprint(company: str, title: str, location: str) -> str:
    return "|".join(_norm(part) for part in (company, title, location))


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
