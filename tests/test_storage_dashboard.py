"""Tests für Dashboard-Storage-Queries (Jobs+Scores gejoint, Feedback-Map)."""
import pytest

from jobscanner import storage
from jobscanner.models import Job


@pytest.fixture(autouse=True)
def db(tmp_path):
    storage.init_db(tmp_path / "jobs.db")
    yield
    storage.close()


def _mk_job(**overrides) -> Job:
    base = dict(title="Unity Dev", company="ACME", location="Hamburg", first_seen="2026-07-11")
    base.update(overrides)
    return Job(**base)


def test_list_jobs_with_scores_joins_profile_score():
    pid = storage.create_profile("Testi", {"skills": []})
    fp = storage.upsert_job(_mk_job())
    storage.upsert_job_score(pid, fp, 87, "passt gut", "Pass",
                             {"role_fit": {"punkte": 9, "grund": "x"}})
    entries = storage.list_jobs_with_scores(pid)
    assert len(entries) == 1
    assert entries[0]["job"].title == "Unity Dev"
    assert entries[0]["score"] == 87
    assert entries[0]["category"] == "Pass"
    assert entries[0]["breakdown"]["role_fit"]["punkte"] == 9


def test_list_jobs_with_scores_none_when_unscored():
    pid = storage.create_profile("Testi", {"skills": []})
    storage.upsert_job(_mk_job())
    entries = storage.list_jobs_with_scores(pid)
    assert entries[0]["score"] is None
    assert entries[0]["breakdown"] == {}


def test_list_jobs_with_scores_newest_first():
    pid = storage.create_profile("Testi", {"skills": []})
    storage.upsert_job(_mk_job(company="Alt", first_seen="2026-07-01"))
    storage.upsert_job(_mk_job(company="Neu", first_seen="2026-07-11"))
    entries = storage.list_jobs_with_scores(pid)
    assert [e["job"].company for e in entries] == ["Neu", "Alt"]


def test_get_feedback_map():
    pid = storage.create_profile("Testi", {"skills": []})
    storage.add_feedback(pid, "fp1", "up")
    storage.add_feedback(pid, "fp2", "down")
    assert storage.get_feedback_map(pid) == {"fp1": "up", "fp2": "down"}
