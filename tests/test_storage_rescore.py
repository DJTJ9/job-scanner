"""Tests für rescore_profile — deterministische Neuberechnung aus breakdown_json."""
import pytest

from jobscanner import storage
from jobscanner.models import Job


@pytest.fixture(autouse=True)
def db(tmp_path):
    storage.init_db(tmp_path / "jobs.db")
    yield
    storage.close()


def _default_profile():
    pid = storage.create_profile("Tjark", {}, is_default=True)
    storage.save_criteria(pid, [{"key": "role_fit", "label": "Rolle", "weight": 5, "sort": 0}])
    return pid


def test_rescore_recomputes_score_after_weight_change():
    pid = _default_profile()
    fp = storage.upsert_job(Job(title="Unity Dev", company="ACME", location="Hamburg",
                                first_seen="2026-07-11"))
    storage.upsert_job_score(pid, fp, 40, "alt", "Vielleicht",
                             {"role_fit": {"punkte": 8, "grund": "passt"}})
    changed = storage.rescore_profile(pid)
    assert changed == [fp]
    assert storage.get_job_score(pid, fp)["score"] == 80
    assert storage.get_job_score(pid, fp)["category"] == "Pass"


def test_rescore_updates_jobs_table_for_default_profile():
    pid = _default_profile()
    fp = storage.upsert_job(Job(title="Unity Dev", company="ACME", location="Hamburg",
                                first_seen="2026-07-11"))
    storage.upsert_job_score(pid, fp, 0, "", "No-Go",
                             {"role_fit": {"punkte": 9, "grund": "x"}})
    storage.rescore_profile(pid)
    assert storage.get_job(fp).score == 90
    assert storage.get_job(fp).category == "Pass"


def test_rescore_skips_veto_rows_with_empty_breakdown():
    pid = _default_profile()
    fp = storage.upsert_job(Job(title="Senior Dev", company="ACME", location="Hamburg",
                                first_seen="2026-07-11"))
    storage.upsert_job_score(pid, fp, 0, "No-Go: Senior", "No-Go", {})
    changed = storage.rescore_profile(pid)
    assert changed == []
    assert storage.get_job_score(pid, fp)["score"] == 0
    assert storage.get_job_score(pid, fp)["category"] == "No-Go"


def test_rescore_non_default_profile_leaves_jobs_table_untouched():
    _default_profile()
    other_pid = storage.create_profile("Zweit", {})
    storage.save_criteria(other_pid,
                          [{"key": "role_fit", "label": "Rolle", "weight": 5, "sort": 0}])
    fp = storage.upsert_job(Job(title="Unity Dev", company="ACME", location="Hamburg",
                                first_seen="2026-07-11"))
    storage.upsert_job_score(other_pid, fp, 10, "", "No-Go",
                             {"role_fit": {"punkte": 7, "grund": "y"}})
    storage.rescore_profile(other_pid)
    assert storage.get_job_score(other_pid, fp)["score"] == 70
    assert storage.get_job(fp).score is None
