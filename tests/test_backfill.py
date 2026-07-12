"""Tests für backfill_scores — Cleanup + Score-Backfill, Groq gemockt."""
import pytest

from jobscanner import backfill_scores, storage
from jobscanner.models import Job


@pytest.fixture()
def db(tmp_path, monkeypatch):
    storage.init_db(tmp_path / "jobs.db")
    monkeypatch.setattr(backfill_scores, "_SLEEP_S", 0)
    yield
    storage.close()


def _indeed_job(title, jk, bb, location="Essen", first_seen="2026-07-10"):
    return Job(title=title, company="ACME", location=location,
               sources=[{"portal": "indeed",
                         "url": f"https://de.indeed.com/viewjob?jk={jk}&bb={bb}",
                         "found_at": first_seen}],
               first_seen=first_seen, last_seen=first_seen)


def _profile():
    pid = storage.create_profile("Testi", {"skills": ["Unity"]}, is_default=True)
    storage.save_criteria(pid, [{"key": "role_fit", "label": "Rolle",
                                 "weight": 5, "sort": 0}])
    return pid


class TestCleanup:
    def test_merges_rows_with_same_jk(self, db):
        storage.upsert_job(_indeed_job("Dev", "abc", "one", location="Essen"))
        storage.upsert_job(_indeed_job("Dev", "abc", "two",
                                       location="Essen oder Würzburg"))
        result = backfill_scores.cleanup_indeed_duplicates()
        assert result["rows_removed"] == 1
        jobs = storage.list_jobs()
        assert len(jobs) == 1
        assert jobs[0].sources[0]["url"] == "https://de.indeed.com/viewjob?jk=abc"

    def test_dry_run_changes_nothing(self, db):
        storage.upsert_job(_indeed_job("Dev", "abc", "one", location="Essen"))
        storage.upsert_job(_indeed_job("Dev", "abc", "two",
                                       location="Essen oder Würzburg"))
        result = backfill_scores.cleanup_indeed_duplicates(dry_run=True)
        assert result["rows_removed"] == 1
        jobs = storage.list_jobs()
        assert len(jobs) == 2
        assert "bb=" in jobs[0].sources[0]["url"]

    def test_canonicalizes_single_row_without_merge(self, db):
        storage.upsert_job(_indeed_job("Dev", "cafe", "xyz"))
        result = backfill_scores.cleanup_indeed_duplicates()
        assert result["rows_removed"] == 0
        assert storage.list_jobs()[0].sources[0]["url"] == \
            "https://de.indeed.com/viewjob?jk=cafe"

    def test_non_indeed_sources_untouched(self, db):
        job = Job(title="Dev", company="ACME", location="Hamburg",
                  sources=[{"portal": "stepstone",
                            "url": "https://stepstone.de/x?jk=trap",
                            "found_at": "2026-07-10"}],
                  first_seen="2026-07-10", last_seen="2026-07-10")
        storage.upsert_job(job)
        backfill_scores.cleanup_indeed_duplicates()
        assert storage.list_jobs()[0].sources[0]["url"] == "https://stepstone.de/x?jk=trap"

    def test_extra_source_on_dropped_row_merges_into_keeper(self, db):
        keeper = _indeed_job("Dev", "abc", "one", location="Essen",
                             first_seen="2026-07-10")
        dropped = _indeed_job("Dev", "abc", "two",
                              location="Essen oder Würzburg",
                              first_seen="2026-07-11")
        dropped.sources.append({"portal": "stepstone",
                                "url": "https://stepstone.de/x?id=99",
                                "found_at": "2026-07-11"})
        storage.upsert_job(keeper)
        storage.upsert_job(dropped)
        result = backfill_scores.cleanup_indeed_duplicates()
        assert result["rows_removed"] == 1
        jobs = storage.list_jobs()
        assert len(jobs) == 1
        urls = {s["url"] for s in jobs[0].sources}
        assert urls == {
            "https://de.indeed.com/viewjob?jk=abc",
            "https://stepstone.de/x?id=99",
        }

    def test_dropped_keeper_of_one_group_resolves_across_groups(self, db):
        # Job1 holds both jk=aaa and jk=bbb (a merged repost row).
        # Job2 (jk=aaa only, oldest) is keeper of the aaa-group -> Job1 gets
        # dropped there. Job3 (jk=bbb only, newest, plus a unique stepstone
        # source) would otherwise see Job1 as the bbb-group's keeper, but
        # Job1 was already deleted while processing the aaa-group first —
        # storage.set_sources on Job1's dead fingerprint is a silent no-op,
        # so Job3's unique stepstone source must not vanish when Job3 is
        # deleted as the bbb-group's "duplicate".
        job1 = Job(title="Dev One", company="ACME", location="Essen",
                   sources=[
                       {"portal": "indeed",
                        "url": "https://de.indeed.com/viewjob?jk=aaa&bb=x",
                        "found_at": "2026-07-05"},
                       {"portal": "indeed",
                        "url": "https://de.indeed.com/viewjob?jk=bbb&bb=x",
                        "found_at": "2026-07-05"},
                   ],
                   first_seen="2026-07-05", last_seen="2026-07-05")
        job2 = _indeed_job("Dev Two", "aaa", "y", first_seen="2026-07-01")
        job3 = _indeed_job("Dev Three", "bbb", "z", first_seen="2026-07-09")
        job3.sources.append({"portal": "stepstone",
                             "url": "https://stepstone.de/x?id=unique",
                             "found_at": "2026-07-09"})
        storage.upsert_job(job1)
        storage.upsert_job(job2)
        storage.upsert_job(job3)

        result = backfill_scores.cleanup_indeed_duplicates()

        jobs = storage.list_jobs()
        urls = {s["url"] for j in jobs for s in j.sources}
        assert urls == {
            "https://de.indeed.com/viewjob?jk=aaa",
            "https://de.indeed.com/viewjob?jk=bbb",
            "https://stepstone.de/x?id=unique",
        }
        assert len(jobs) == 1
        assert result["rows_removed"] == 2


class TestBackfill:
    def test_scores_only_jobs_without_score(self, db, monkeypatch):
        pid = _profile()
        monkeypatch.setattr(backfill_scores.storage, "migrate_yaml_profile", lambda: None)
        fp1 = storage.upsert_job(_indeed_job("Scored", "s1", "b"))
        fp2 = storage.upsert_job(_indeed_job("Unscored", "s2", "b"))
        storage.upsert_job_score(pid, fp1, 80, "ok", "Pass", {})
        scored = []
        monkeypatch.setattr(backfill_scores.scoring, "criteria_score",
                            lambda job, prof, crits, feedback=None:
                            scored.append(job.title)
                            or (60, "ok", "Vielleicht", {}))
        stats = backfill_scores.backfill()
        assert scored == ["Unscored"]
        assert storage.get_job_score(pid, fp2)["score"] == 60
        assert stats == {"Testi:Vielleicht": 1}

    def test_mirrors_default_profile_score_to_jobs_table(self, db, monkeypatch):
        pid = _profile()
        monkeypatch.setattr(backfill_scores.storage, "migrate_yaml_profile", lambda: None)
        fp = storage.upsert_job(_indeed_job("Dev", "m1", "b"))
        monkeypatch.setattr(backfill_scores.scoring, "criteria_score",
                            lambda job, prof, crits, feedback=None:
                            (85, "Top", "Pass", {}))
        backfill_scores.backfill()
        job = storage.get_job(fp)
        assert job.score == 85 and job.category == "Pass"

    def test_error_result_not_persisted_for_retry(self, db, monkeypatch):
        pid = _profile()
        monkeypatch.setattr(backfill_scores.storage, "migrate_yaml_profile", lambda: None)
        fp = storage.upsert_job(_indeed_job("Dev", "e1", "b"))
        monkeypatch.setattr(backfill_scores.scoring, "criteria_score",
                            lambda job, prof, crits, feedback=None:
                            (None, "Scoring-Fehler: API down", None, {}))
        stats = backfill_scores.backfill()
        assert stats == {"errors": 1}
        assert storage.get_job_score(pid, fp) is None

    def test_passes_feedback_to_scoring(self, db, monkeypatch):
        pid = _profile()
        monkeypatch.setattr(backfill_scores.storage, "migrate_yaml_profile", lambda: None)
        fp_old = storage.upsert_job(_indeed_job("Liked Job", "f0", "b"))
        storage.add_feedback(pid, fp_old, "up")
        storage.upsert_job_score(pid, fp_old, 90, "ok", "Pass", {})
        storage.upsert_job(_indeed_job("New Job", "f1", "b"))
        seen = {}
        monkeypatch.setattr(backfill_scores.scoring, "criteria_score",
                            lambda job, prof, crits, feedback=None:
                            seen.update({"fb": feedback})
                            or (50, "ok", "Vielleicht", {}))
        backfill_scores.backfill()
        assert seen["fb"] == [{"vote": "up", "title": "Liked Job"}]
