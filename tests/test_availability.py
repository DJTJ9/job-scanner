"""Tests für die Verfügbarkeits-Heuristik + Strike-Lauf."""
from datetime import date, timedelta

import pytest

from jobscanner import availability, storage
from jobscanner.models import Job


@pytest.fixture()
def db(tmp_path):
    storage.init_db(tmp_path / "jobs.db")
    yield
    storage.close()


def _old_job(fp_seed: str, url: str) -> str:
    old = (date.today() - timedelta(days=5)).isoformat()
    job = Job(title=f"Dev {fp_seed}", company=f"ACME {fp_seed}", location="Hamburg",
              language="de", requirements=["Unity"], tech_stack=["Unity"],
              sources=[{"portal": "indeed", "url": url, "found_at": old}],
              first_seen=old, last_seen=old)
    return storage.upsert_job(job)


def _strikes(fp):
    return storage._require_conn().execute(
        "SELECT unavailable_strikes FROM jobs WHERE fingerprint = ?", (fp,)).fetchone()[0]


def _status(fp):
    return storage._require_conn().execute(
        "SELECT status FROM jobs WHERE fingerprint = ?", (fp,)).fetchone()[0]


DETAIL = "https://indeed.test/detail/123"


class TestClassify:
    def test_404_is_gone(self):
        assert availability.classify(DETAIL, {"status": 404, "final_url": DETAIL, "html": ""}) == "gone"

    def test_410_is_gone(self):
        assert availability.classify(DETAIL, {"status": 410, "final_url": DETAIL, "html": ""}) == "gone"

    def test_redirect_away_from_detail_is_gone(self):
        rendered = {"status": 200, "final_url": "https://indeed.test/jobs", "html": "<html>Suche</html>"}
        assert availability.classify(DETAIL, rendered) == "gone"

    def test_text_marker_is_gone(self):
        html = "<html><body>Diese Stellenanzeige ist nicht mehr verfügbar.</body></html>"
        assert availability.classify(DETAIL, {"status": 200, "final_url": DETAIL, "html": html}) == "gone"

    def test_alive_with_job_content(self):
        html = ("<html><body>Ihre Aufgaben und Anforderungen: Unity, C#. "
                "Wir bieten eine Vollzeit-Stelle. Jetzt bewerben.</body></html>")
        assert availability.classify(DETAIL, {"status": 200, "final_url": DETAIL, "html": html}) == "alive"

    def test_render_failure_is_unclear(self):
        assert availability.classify(DETAIL, None) == "unclear"

    def test_ambiguous_page_is_unclear(self):
        # 200, kein Weg-Marker, aber auch kein erkennbarer Job-Inhalt (z.B. leere/Block-Seite)
        assert availability.classify(DETAIL, {"status": 200, "final_url": DETAIL, "html": "<html></html>"}) == "unclear"


class TestCheckAll:
    def test_gone_increments_strike(self, db, monkeypatch):
        fp = _old_job("g", "https://indeed.test/g")
        monkeypatch.setattr(availability, "_render_with_status",
                            lambda url: {"status": 404, "final_url": url, "html": ""})
        availability.check_all()
        assert _strikes(fp) == 1
        assert _status(fp) != "expired"

    def test_two_strikes_expire(self, db, monkeypatch):
        fp = _old_job("g2", "https://indeed.test/g2")
        monkeypatch.setattr(availability, "_render_with_status",
                            lambda url: {"status": 404, "final_url": url, "html": ""})
        availability.check_all()
        availability.check_all()
        assert _status(fp) == "expired"

    def test_alive_resets_strike(self, db, monkeypatch):
        fp = _old_job("a", "https://indeed.test/a")
        storage.bump_unavailable_strike(fp)
        alive = ("<html>Aufgaben Anforderungen Unity Vollzeit bewerben wir bieten</html>")
        monkeypatch.setattr(availability, "_render_with_status",
                            lambda url: {"status": 200, "final_url": url, "html": alive})
        availability.check_all()
        assert _strikes(fp) == 0

    def test_unclear_leaves_strike_untouched(self, db, monkeypatch):
        fp = _old_job("u", "https://indeed.test/u")
        storage.bump_unavailable_strike(fp)
        monkeypatch.setattr(availability, "_render_with_status", lambda url: None)
        availability.check_all()
        assert _strikes(fp) == 1
        assert _status(fp) != "expired"
