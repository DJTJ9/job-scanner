"""Tests für den datum-basierten Jinja-Filter relzeit_datum."""
from datetime import date, timedelta

from jobscanner.web.app import relzeit_datum


def _iso(days_ago: int) -> str:
    return (date.today() - timedelta(days=days_ago)).isoformat()


def test_heute():
    assert relzeit_datum(_iso(0)) == f"heute ({date.today():%d.%m.})"


def test_gestern():
    d = date.today() - timedelta(days=1)
    assert relzeit_datum(_iso(1)) == f"gestern ({d:%d.%m.})"


def test_vor_n_tagen():
    d = date.today() - timedelta(days=3)
    assert relzeit_datum(_iso(3)) == f"vor 3 Tagen ({d:%d.%m.})"


def test_leer_und_none():
    assert relzeit_datum("") == ""
    assert relzeit_datum(None) == ""


def test_zukunft_wird_wie_heute():
    morgen = (date.today() + timedelta(days=1)).isoformat()
    assert relzeit_datum(morgen) == f"heute ({date.today():%d.%m.})"


def test_format_hat_datum_in_klammern():
    out = relzeit_datum(_iso(5))
    assert out.endswith(")")
    assert "(" in out and "." in out
