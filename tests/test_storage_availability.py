"""Tests für den Verfügbarkeits-Check: Migration, Kandidaten-Auswahl, Strike-Helper."""
from datetime import date, timedelta

import pytest

from jobscanner import storage
from jobscanner.models import Job


@pytest.fixture()
def db(tmp_path):
    storage.init_db(tmp_path / "jobs.db")
    yield
    storage.close()


def _job(fp_seed: str, last_seen: str, url: str) -> Job:
    return Job(
        title=f"Dev {fp_seed}", company=f"ACME {fp_seed}", location="Hamburg",
        remote_flag="hybrid", employment_type="vollzeit", language="de",
        requirements=["Unity"], tech_stack=["Unity"],
        sources=[{"portal": "indeed", "url": url, "found_at": last_seen}],
        first_seen=last_seen, last_seen=last_seen,
    )


def _strikes(fp: str) -> int:
    row = storage._require_conn().execute(
        "SELECT unavailable_strikes FROM jobs WHERE fingerprint = ?", (fp,)).fetchone()
    return row["unavailable_strikes"]


def _status(fp: str) -> str:
    row = storage._require_conn().execute(
        "SELECT status FROM jobs WHERE fingerprint = ?", (fp,)).fetchone()
    return row["status"]


class TestMigration:
    def test_unavailable_strikes_column_defaults_zero(self, db):
        fp = storage.upsert_job(_job("a", "2026-07-01", "https://indeed.test/a"))
        assert _strikes(fp) == 0


class TestCandidates:
    def test_only_jobs_older_than_threshold(self, db):
        old = (date.today() - timedelta(days=5)).isoformat()
        fresh = (date.today() - timedelta(days=1)).isoformat()
        fp_old = storage.upsert_job(_job("old", old, "https://indeed.test/old"))
        storage.upsert_job(_job("fresh", fresh, "https://indeed.test/fresh"))
        cands = storage.list_availability_candidates(older_than_days=3)
        fps = {c["fingerprint"] for c in cands}
        assert fp_old in fps
        assert all(c["fingerprint"] != "" for c in cands)
        assert len(fps) == 1

    def test_excludes_expired(self, db):
        old = (date.today() - timedelta(days=5)).isoformat()
        fp = storage.upsert_job(_job("x", old, "https://indeed.test/x"))
        storage.mark_expired(fp)
        assert storage.list_availability_candidates(older_than_days=3) == []

    def test_candidate_carries_first_source_url(self, db):
        old = (date.today() - timedelta(days=5)).isoformat()
        fp = storage.upsert_job(_job("u", old, "https://indeed.test/u"))
        cand = next(c for c in storage.list_availability_candidates() if c["fingerprint"] == fp)
        assert cand["url"] == "https://indeed.test/u"


class TestStrikeHelpers:
    def test_bump_increments_and_returns_new_value(self, db):
        fp = storage.upsert_job(_job("b", "2026-07-01", "https://indeed.test/b"))
        assert storage.bump_unavailable_strike(fp) == 1
        assert storage.bump_unavailable_strike(fp) == 2
        assert _strikes(fp) == 2

    def test_reset_zeroes(self, db):
        fp = storage.upsert_job(_job("r", "2026-07-01", "https://indeed.test/r"))
        storage.bump_unavailable_strike(fp)
        storage.reset_unavailable_strike(fp)
        assert _strikes(fp) == 0

    def test_mark_expired_sets_status(self, db):
        fp = storage.upsert_job(_job("e", "2026-07-01", "https://indeed.test/e"))
        storage.mark_expired(fp)
        assert _status(fp) == "expired"


class TestExpiredExcludedFromQueries:
    def _scored_extracted(self, fp_seed: str, url: str, last_seen: str = "2026-07-01"):
        # Job über upsert_job anlegen (extraction_status default 'extracted'),
        # dann Score setzen → erscheint in allen Score-/Dashboard-Queries.
        fp = storage.upsert_job(_job(fp_seed, last_seen, url))
        storage.update_job(fp, score=90, score_reason="gut", category="Pass")
        return fp

    def test_expired_absent_from_list_jobs_with_scores(self, db):
        pid = storage.create_profile("Test", {})
        fp = self._scored_extracted("j", "https://indeed.test/j")
        storage.upsert_job_score(pid, fp, 90, "gut", "Pass", {})
        assert any(e["job"].fingerprint == fp for e in storage.list_jobs_with_scores(pid))
        storage.mark_expired(fp)
        assert all(e["job"].fingerprint != fp for e in storage.list_jobs_with_scores(pid))

    def test_expired_absent_from_list_unscored_extracted(self, db):
        fp = storage.upsert_job(_job("u1", "2026-07-01", "https://indeed.test/u1"))
        assert any(x["fingerprint"] == fp for x in storage.list_unscored_extracted())
        storage.mark_expired(fp)
        assert all(x["fingerprint"] != fp for x in storage.list_unscored_extracted())

    def test_expired_absent_from_list_unscored_for_profiles(self, db):
        pid = storage.create_profile("Test", {})
        fp = storage.upsert_job(_job("u2", "2026-07-01", "https://indeed.test/u2"))
        assert any(x["fingerprint"] == fp for x in storage.list_unscored_for_profiles([pid]))
        storage.mark_expired(fp)
        assert all(x["fingerprint"] != fp for x in storage.list_unscored_for_profiles([pid]))

    def test_expired_absent_from_list_pending_extraction(self, db):
        fp = storage.insert_raw_job("https://indeed.test/p", "indeed", "roh text", "2026-07-01")
        assert any(x["fingerprint"] == fp for x in storage.list_pending_extraction())
        storage.mark_expired(fp)
        assert all(x["fingerprint"] != fp for x in storage.list_pending_extraction())

    def test_expired_absent_from_list_unnotified_top_matches(self, db):
        pid = storage.create_profile("Test", {})
        fp = storage.upsert_job(_job("n", "2026-07-01", "https://indeed.test/n"))
        storage.upsert_job_score(pid, fp, 95, "top", "Pass", {})
        assert any(m["fingerprint"] == fp for m in storage.list_unnotified_top_matches(pid))
        storage.mark_expired(fp)
        assert all(m["fingerprint"] != fp for m in storage.list_unnotified_top_matches(pid))
