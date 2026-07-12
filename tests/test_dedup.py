"""Tests für Dedup-Hilfen gegen Test-DB."""
import pytest

from jobscanner import dedup, storage
from jobscanner.models import Job


@pytest.fixture()
def db(tmp_path):
    storage.init_db(tmp_path / "jobs.db")
    yield
    storage.close()


def _job(url: str, **overrides) -> Job:
    base = dict(
        title="Unity Developer", company="ACME GmbH", location="Hamburg",
        sources=[{"portal": "stepstone", "url": url, "found_at": "2026-07-09"}],
        first_seen="2026-07-09", last_seen="2026-07-09",
    )
    base.update(overrides)
    return Job(**base)


def test_known_source_urls_maps_url_to_fingerprint(db):
    job = _job("https://example.com/job/1")
    storage.upsert_job(job)
    known = dedup.known_source_urls()
    assert known == {"https://example.com/job/1": job.fingerprint}


def test_touch_known_updates_last_seen_only(db):
    job = _job("https://example.com/job/1")
    fp = storage.upsert_job(job)
    dedup.touch_known(fp, "2026-07-10")
    stored = storage.get_job(fp)
    assert stored.last_seen == "2026-07-10"
    assert stored.first_seen == "2026-07-09"  # Frische-Semantik: bleibt


class TestCanonicalizeUrl:
    def test_indeed_viewjob_strips_tracking_params(self):
        url = "https://de.indeed.com/viewjob?jk=abc123&bb=volatile&from=serp"
        assert dedup.canonicalize_url(url, "indeed") == "https://de.indeed.com/viewjob?jk=abc123"

    def test_indeed_rc_clk_maps_to_viewjob(self):
        url = "https://de.indeed.com/rc/clk?jk=deadbeef01&bb=xyz"
        assert dedup.canonicalize_url(url, "indeed") == "https://de.indeed.com/viewjob?jk=deadbeef01"

    def test_indeed_without_jk_unchanged(self):
        url = "https://de.indeed.com/jobs?q=unity"
        assert dedup.canonicalize_url(url, "indeed") == url

    def test_other_portal_unchanged(self):
        url = "https://www.stepstone.de/stellenangebote--x?jk=trap"
        assert dedup.canonicalize_url(url, "stepstone") == url
