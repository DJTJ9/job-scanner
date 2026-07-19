"""Tests für llm_batch — CLI-Schnittstelle für den Agent-Batch-Lauf, kein LLM gemockt
(Agent liefert Extraktion+Scoring bereits als fertiges JSON)."""
from unittest.mock import patch

import pytest

from jobscanner import llm_batch, storage
from jobscanner.models import Job


@pytest.fixture()
def db(tmp_path):
    storage.init_db(tmp_path / "jobs.db")
    yield tmp_path / "jobs.db"
    storage.close()


def _profile(db_path):
    pid = storage.create_profile("Testi", {"no_gos": ["Zeitarbeit"]}, is_default=True)
    storage.save_criteria(pid, [{"key": "role_fit", "label": "Rolle", "weight": 5, "sort": 0}])
    return pid


class TestListPending:
    def test_returns_pending_jobs_and_profiles(self, db):
        pid = _profile(db)
        storage.insert_raw_job("https://a.test/1", "indeed", "Rohtext", "2026-07-12")
        result = llm_batch.list_pending(db)
        assert len(result["jobs"]) == 1
        assert result["jobs"][0]["raw_text"] == "Rohtext"
        assert result["profiles"][0]["id"] == pid
        assert result["profiles"][0]["criteria"][0]["key"] == "role_fit"

    def test_respects_limit(self, db):
        _profile(db)
        for i in range(3):
            storage.insert_raw_job(f"https://a.test/{i}", "indeed", "T", "2026-07-12")
        result = llm_batch.list_pending(db, limit=2)
        assert len(result["jobs"]) == 2


class TestWriteBatch:
    def test_extracts_and_scores_job(self, db):
        pid = _profile(db)
        raw_fp = storage.insert_raw_job("https://a.test/1", "indeed", "Text", "2026-07-12")
        entries = [{
            "fingerprint": raw_fp,
            "extraction": {"title": "Unity Developer", "company": "ACME",
                          "location": "Hamburg", "remote": "hybrid"},
            "scores": {str(pid): {"veto": None,
                                  "kriterien": {"role_fit": {"punkte": 8, "grund": "passt"}}}},
        }]
        with patch("jobscanner.llm_batch.nocodb_board.push_job", return_value=42):
            stats = llm_batch.write_batch(entries, db, today="2026-07-12")
        assert stats == {"extracted": 1, "skipped_extraction": 0, "scored": 1,
                         "skipped_scoring": 0}
        job_score = storage.get_job_score(pid, storage.list_jobs()[0].fingerprint)
        assert job_score["score"] == 80
        assert job_score["category"] == "Pass"

    def test_skips_extraction_when_title_missing(self, db):
        _profile(db)
        raw_fp = storage.insert_raw_job("https://a.test/1", "indeed", "Text", "2026-07-12")
        entries = [{"fingerprint": raw_fp, "extraction": {"company": "ACME"}, "scores": {}}]
        stats = llm_batch.write_batch(entries, db, today="2026-07-12")
        assert stats["skipped_extraction"] == 1
        assert storage.list_pending_extraction() == [{
            "fingerprint": raw_fp, "portal": "indeed", "url": "https://a.test/1",
            "raw_text": "Text"}]

    def test_regex_veto_overrides_agent_score(self, db):
        pid = _profile(db)
        raw_fp = storage.insert_raw_job("https://a.test/1", "indeed", "Text", "2026-07-12")
        entries = [{
            "fingerprint": raw_fp,
            "extraction": {"title": "Senior Unity Developer", "company": "ACME"},
            "scores": {str(pid): {"veto": None,
                                  "kriterien": {"role_fit": {"punkte": 10, "grund": "top"}}}},
        }]
        with patch("jobscanner.llm_batch.nocodb_board.push_job", return_value=1):
            llm_batch.write_batch(entries, db, today="2026-07-12")
        job = storage.list_jobs()[0]
        score = storage.get_job_score(pid, job.fingerprint)
        assert score["category"] == "No-Go"
        assert "Senior" in score["reason"]

    def test_pass_category_archives_and_pushes_nocodb(self, db):
        pid = _profile(db)
        raw_fp = storage.insert_raw_job("https://a.test/1", "indeed", "Text", "2026-07-12")
        entries = [{
            "fingerprint": raw_fp,
            "extraction": {"title": "Unity Developer", "company": "ACME"},
            "scores": {str(pid): {"veto": None,
                                  "kriterien": {"role_fit": {"punkte": 10, "grund": "top"}}}},
        }]
        with patch("jobscanner.llm_batch.nocodb_board.push_job", return_value=99) as push, \
             patch("jobscanner.llm_batch.archive.save_snapshot", return_value="/tmp/x.md") as arch:
            llm_batch.write_batch(entries, db, today="2026-07-12")
        assert arch.called
        push.assert_called_once()
        job = storage.list_jobs()[0]
        assert job.nocodb_row_id == 99
        assert job.archive_path == "/tmp/x.md"

    def test_no_nocodb_flag_skips_push(self, db):
        pid = _profile(db)
        raw_fp = storage.insert_raw_job("https://a.test/1", "indeed", "Text", "2026-07-12")
        entries = [{"fingerprint": raw_fp,
                   "extraction": {"title": "Unity Developer", "company": "ACME"},
                   "scores": {}}]
        with patch("jobscanner.llm_batch.nocodb_board.push_job") as push:
            llm_batch.write_batch(entries, db, today="2026-07-12", push_nocodb=False)
        push.assert_not_called()

    def test_none_score_result_not_persisted(self, db):
        pid = _profile(db)
        raw_fp = storage.insert_raw_job("https://a.test/1", "indeed", "Text", "2026-07-12")
        entries = [{
            "fingerprint": raw_fp,
            "extraction": {"title": "Unity Developer", "company": "ACME"},
            "scores": {str(pid): {"veto": None,
                                  "kriterien": {"role_fit": {"punkte": None, "grund": "?"}}}},
        }]
        with patch("jobscanner.llm_batch.nocodb_board.push_job", return_value=1):
            stats = llm_batch.write_batch(entries, db, today="2026-07-12")
        assert stats["skipped_scoring"] == 1
        job = storage.list_jobs()[0]
        assert storage.get_job_score(pid, job.fingerprint) is None


class TestScoreOnly:
    def test_list_pending_includes_to_score(self, db):
        _profile(db)
        fp = storage.upsert_job(Job(title="Waise", company="ACME", location="Hamburg",
                                    first_seen="2026-07-12"))
        result = llm_batch.list_pending(db)
        assert result["jobs"] == []
        assert len(result["to_score"]) == 1
        assert result["to_score"][0]["fingerprint"] == fp

    def test_write_batch_scores_without_extraction(self, db):
        pid = _profile(db)
        fp = storage.upsert_job(Job(title="Unity Developer", company="ACME",
                                    location="Hamburg", first_seen="2026-07-12"))
        entries = [{"fingerprint": fp,
                    "scores": {str(pid): {"veto": None,
                        "kriterien": {"role_fit": {"punkte": 6, "grund": "ok"}}}}}]
        with patch("jobscanner.llm_batch.nocodb_board.push_job", return_value=7):
            stats = llm_batch.write_batch(entries, db, today="2026-07-12")
        assert stats["extracted"] == 0
        assert stats["scored"] == 1
        assert storage.get_job_score(pid, fp)["score"] == 60
        assert storage.get_job(fp).score == 60

    def test_write_batch_score_only_missing_job_skips(self, db):
        _profile(db)
        entries = [{"fingerprint": "does|not|exist", "scores": {}}]
        stats = llm_batch.write_batch(entries, db, today="2026-07-12")
        assert stats["skipped_scoring"] == 1


class TestRuleFilterPreSkip:
    @staticmethod
    def _active_profile():
        pid = storage.create_profile("Testi", {}, is_default=True)
        storage.save_criteria(
            pid, [{"key": "role_fit", "label": "Rolle", "weight": 5, "sort": 0}])
        return pid

    @staticmethod
    def _extracted_job(title, employment_type=""):
        return storage.upsert_job(Job(title=title, company="ACME", location="Hamburg",
                                      employment_type=employment_type, first_seen="2026-07-12"))

    def test_list_pending_preskips_rule_filter_no_go(self, db):
        pid = self._active_profile()
        fp = self._extracted_job(title="Senior Unity Developer", employment_type="Vollzeit")
        pending = llm_batch.list_pending(db)
        assert fp not in {j["fingerprint"] for j in pending["to_score"]}
        sc = storage.get_job_score(pid, fp)
        assert sc["category"] == "No-Go" and sc["score"] == 0

    def test_list_pending_keeps_non_no_go(self, db):
        pid = self._active_profile()
        fp = self._extracted_job(title="Junior Unity Developer", employment_type="Vollzeit")
        pending = llm_batch.list_pending(db)
        assert fp in {j["fingerprint"] for j in pending["to_score"]}
        assert storage.get_job_score(pid, fp) is None

    def test_preskip_logs_saved_scoring(self, db):
        self._active_profile()
        self._extracted_job(title="Senior Engineer", employment_type="Vollzeit")
        llm_batch.list_pending(db)
        conn = storage._require_conn()
        rows = conn.execute(
            "SELECT event_type FROM events WHERE event_type='scoring_saved'").fetchall()
        assert len(rows) >= 1


def test_list_pending_includes_profile_preferences(tmp_path):
    from jobscanner import storage
    from jobscanner import llm_batch
    storage.init_db(tmp_path / "jobs.db")
    pid = storage.create_profile(
        "Tjark", {"preferences": ["Hamburg stark bepunkten", "Remote bevorzugt"]},
        is_default=True)
    storage.save_criteria(pid, [{"key": "role_fit", "label": "Rolle", "weight": 5, "sort": 0}])
    result = llm_batch.list_pending(tmp_path / "jobs.db")
    prof = next(p for p in result["profiles"] if p["id"] == pid)
    assert prof["preferences"] == ["Hamburg stark bepunkten", "Remote bevorzugt"]
    storage.close()
