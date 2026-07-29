# tests/test_export.py
"""Tests für Match-Export: CSV/PDF-Builder, /export-Route, Dialog-Präsenz."""
import pytest

from jobscanner import storage
from jobscanner.models import Job
from jobscanner.web import export


def _mk_entry(title="Unity Dev", company="ACME", location="Hamburg",
              score=92, category="Pass", reason="passt gut",
              sources=None, first_seen="2026-07-11"):
    if sources is None:
        sources = [{"portal": "stepstone", "url": "https://example.com/j/1",
                    "found_at": "2026-07-11"}]
    job = Job(title=title, company=company, location=location,
              first_seen=first_seen, sources=sources)
    return {"job": job, "score": score, "reason": reason, "category": category,
            "breakdown": {}, "scored_at": "2026-07-11", "is_ausland": False}


def test_build_csv_bom_header_and_row():
    entry = _mk_entry()
    fp = entry["job"].fingerprint
    data = export.build_csv([entry], {fp})
    assert data.startswith(b"\xef\xbb\xbf")
    lines = data.decode("utf-8-sig").splitlines()
    assert lines[0] == "titel;firma;ort;score;kategorie;begruendung;portal;erstgesehen;link;favorit"
    assert lines[1] == "Unity Dev;ACME;Hamburg;92;Pass;passt gut;stepstone;2026-07-11;https://example.com/j/1;ja"


def test_build_csv_none_score_no_sources_nicht_favorit():
    entry = _mk_entry(score=None, category=None, reason=None, sources=[])
    data = export.build_csv([entry], set())
    row = data.decode("utf-8-sig").splitlines()[1]
    assert row == "Unity Dev;ACME;Hamburg;;;;;2026-07-11;;nein"


def test_build_csv_quotes_semicolon_in_begruendung():
    entry = _mk_entry(reason="gut; aber remote")
    row = export.build_csv([entry], set()).decode("utf-8-sig").splitlines()[1]
    assert '"gut; aber remote"' in row


def test_build_csv_unsafe_scheme_leerer_link():
    entry = _mk_entry(sources=[{"portal": "x", "url": "javascript:alert(1)"}])
    row = export.build_csv([entry], set()).decode("utf-8-sig").splitlines()[1]
    assert "javascript" not in row
