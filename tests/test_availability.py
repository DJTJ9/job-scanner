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


class TestApplyVerdict:
    def test_gone_bumps_strike_expires_on_second(self, db):
        fp = _old_job("g1", "https://indeed.com/j/1")
        assert availability.apply_verdict(fp, "gone") is False
        assert storage.get_job(fp).status != "expired"
        assert availability.apply_verdict(fp, "gone") is True
        assert storage.get_job(fp).status == "expired"

    def test_alive_resets_strike(self, db):
        fp = _old_job("a1", "https://indeed.com/j/2")
        availability.apply_verdict(fp, "gone")          # strike = 1
        availability.apply_verdict(fp, "alive")         # reset
        assert availability.apply_verdict(fp, "gone") is False  # wieder bei 1, kein expire
        assert storage.get_job(fp).status != "expired"

    def test_unclear_leaves_counter_untouched(self, db):
        fp = _old_job("u1", "https://indeed.com/j/3")
        availability.apply_verdict(fp, "gone")          # strike = 1
        assert availability.apply_verdict(fp, "unclear") is False
        assert availability.apply_verdict(fp, "gone") is True   # 1 -> 2 -> expire
        assert storage.get_job(fp).status == "expired"
