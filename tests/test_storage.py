"""Tests für models.fingerprint + storage-Schicht (CRUD, Upsert)."""
import pytest

from jobscanner.models import Job, make_fingerprint


class TestFingerprint:
    def test_normalizes_case_and_whitespace(self):
        assert make_fingerprint("ACME  GmbH", "Unity   Developer", "Hamburg ") == \
            make_fingerprint("acme gmbh", "unity developer", "hamburg")

    def test_strips_punctuation(self):
        assert make_fingerprint("ACME GmbH & Co. KG", "C++/Unity-Dev (m/w/d)", "Köln") == \
            make_fingerprint("acme gmbh co kg", "c unity dev m w d", "köln")

    def test_different_jobs_differ(self):
        a = make_fingerprint("ACME", "Unity Developer", "Hamburg")
        b = make_fingerprint("ACME", "Unreal Developer", "Hamburg")
        assert a != b

    def test_job_property_matches_helper(self):
        job = Job(title="Unity Developer", company="ACME", location="Hamburg")
        assert job.fingerprint == make_fingerprint("ACME", "Unity Developer", "Hamburg")

    def test_strips_legal_suffix_gmbh(self):
        assert make_fingerprint("ACME GmbH", "Unity Developer", "Hamburg") == \
            make_fingerprint("ACME", "Unity Developer", "Hamburg")

    def test_strips_legal_suffix_combined_gmbh_co_kg(self):
        assert make_fingerprint("ACME GmbH & Co. KG", "Unity Developer", "Hamburg") == \
            make_fingerprint("ACME", "Unity Developer", "Hamburg")

    @pytest.mark.parametrize("suffix", ["AG", "UG", "KG", "OHG", "GbR", "mbH", "e.V."])
    def test_strips_various_legal_suffixes(self, suffix):
        assert make_fingerprint(f"ACME {suffix}", "Unity Developer", "Hamburg") == \
            make_fingerprint("ACME", "Unity Developer", "Hamburg")

    def test_unmatched_suffix_still_differs(self):
        a = make_fingerprint("ACME AG", "Unity Developer", "Hamburg")
        b = make_fingerprint("ACME Corp", "Unity Developer", "Hamburg")
        assert a != b

    def test_company_that_is_only_suffix_word_not_emptied(self):
        assert make_fingerprint("AG", "Unity Developer", "Hamburg") != \
            make_fingerprint("", "Unity Developer", "Hamburg")

    def test_none_values_treated_as_empty_string(self):
        assert make_fingerprint(None, "Unity Developer", None) == \
            make_fingerprint("", "Unity Developer", "")


from jobscanner import storage


@pytest.fixture()
def db(tmp_path):
    storage.init_db(tmp_path / "jobs.db")
    yield
    storage.close()


def _job(**overrides) -> Job:
    base = dict(
        title="Unity Developer",
        company="ACME GmbH",
        location="Hamburg",
        remote_flag="hybrid",
        employment_type="vollzeit",
        language="de",
        salary_text="50-60k",
        requirements=["Unity", "C#"],
        tech_stack=["Unity", "C#", "Git"],
        sources=[{"portal": "indeed", "url": "https://indeed.test/1", "found_at": "2026-07-10"}],
        first_seen="2026-07-10",
        last_seen="2026-07-10",
    )
    base.update(overrides)
    return Job(**base)


class TestStorage:
    def test_roundtrip_write_read(self, db):
        job = _job()
        fp = storage.upsert_job(job)
        loaded = storage.get_job(fp)
        assert loaded is not None
        assert loaded.title == "Unity Developer"
        assert loaded.requirements == ["Unity", "C#"]
        assert loaded.sources[0]["portal"] == "indeed"
        assert loaded.status == "neu"

    def test_get_unknown_returns_none(self, db):
        assert storage.get_job("nix|da|hier") is None

    def test_upsert_updates_instead_of_duplicating(self, db):
        storage.upsert_job(_job())
        again = _job(
            last_seen="2026-07-11",
            sources=[{"portal": "stepstone", "url": "https://stepstone.test/9", "found_at": "2026-07-11"}],
        )
        fp = storage.upsert_job(again)
        assert len(storage.list_jobs()) == 1
        loaded = storage.get_job(fp)
        assert loaded.last_seen == "2026-07-11"
        assert {s["portal"] for s in loaded.sources} == {"indeed", "stepstone"}

    def test_upsert_does_not_duplicate_same_source_url(self, db):
        storage.upsert_job(_job())
        storage.upsert_job(_job(last_seen="2026-07-11"))
        assert len(storage.get_job(_job().fingerprint).sources) == 1

    def test_update_job_fields(self, db):
        fp = storage.upsert_job(_job())
        storage.update_job(fp, score=87, score_reason="Kern-Match Unity", status="interessant", nocodb_row_id=42)
        loaded = storage.get_job(fp)
        assert (loaded.score, loaded.status, loaded.nocodb_row_id) == (87, "interessant", 42)

    def test_update_job_rejects_unknown_field(self, db):
        fp = storage.upsert_job(_job())
        with pytest.raises(ValueError):
            storage.update_job(fp, fingerprint="hack")

    def test_role_field_roundtrips(self, db):
        fp = storage.upsert_job(_job(role="unity_games"))
        loaded = storage.get_job(fp)
        assert loaded.role == "unity_games"

    def test_init_db_migrates_pre_role_schema(self, tmp_path):
        import sqlite3
        db_path = tmp_path / "old.db"
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE jobs (
                id INTEGER PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL, company TEXT NOT NULL, location TEXT,
                remote_flag TEXT, employment_type TEXT, language TEXT, salary_text TEXT,
                requirements_json TEXT, tech_stack_json TEXT, sources_json TEXT,
                first_seen TEXT, last_seen TEXT, archive_path TEXT, score INTEGER,
                score_reason TEXT, category TEXT, status TEXT DEFAULT 'neu', nocodb_row_id INTEGER
            )
        """)
        conn.commit()
        conn.close()
        storage.init_db(db_path)
        fp = storage.upsert_job(_job(role="unity_games"))
        assert storage.get_job(fp).role == "unity_games"
        storage.close()

    def test_is_neighbor_field_roundtrips(self, db):
        fp = storage.upsert_job(_job(is_neighbor=True))
        assert storage.get_job(fp).is_neighbor is True

    def test_is_neighbor_defaults_to_false(self, db):
        fp = storage.upsert_job(_job())
        assert storage.get_job(fp).is_neighbor is False

    def test_init_db_migrates_pre_is_neighbor_schema(self, tmp_path):
        import sqlite3
        db_path = tmp_path / "old.db"
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE jobs (
                id INTEGER PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL, company TEXT NOT NULL, location TEXT,
                remote_flag TEXT, employment_type TEXT, language TEXT, salary_text TEXT,
                role TEXT, requirements_json TEXT, tech_stack_json TEXT, sources_json TEXT,
                first_seen TEXT, last_seen TEXT, archive_path TEXT, score INTEGER,
                score_reason TEXT, category TEXT, status TEXT DEFAULT 'neu', nocodb_row_id INTEGER
            )
        """)
        conn.commit()
        conn.close()
        storage.init_db(db_path)
        fp = storage.upsert_job(_job(is_neighbor=True))
        assert storage.get_job(fp).is_neighbor is True
        storage.close()

    def test_init_db_migrates_pre_is_ausland_schema(self, tmp_path):
        import sqlite3
        db_path = tmp_path / "old.db"
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE jobs (
                id INTEGER PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL, company TEXT NOT NULL, location TEXT,
                remote_flag TEXT, employment_type TEXT, language TEXT, salary_text TEXT,
                role TEXT, is_neighbor INTEGER DEFAULT 0, requirements_json TEXT,
                tech_stack_json TEXT, sources_json TEXT, first_seen TEXT, last_seen TEXT,
                archive_path TEXT, score INTEGER, score_reason TEXT, category TEXT,
                status TEXT DEFAULT 'neu', nocodb_row_id INTEGER, raw_text TEXT,
                extraction_status TEXT DEFAULT 'extracted'
            )
        """)
        conn.commit()
        conn.close()
        storage.init_db(db_path)
        pid = storage.create_profile("Testi", {}, is_default=True)
        storage.upsert_job(_job())
        entries = storage.list_jobs_with_scores(pid)
        assert entries[0]["is_ausland"] is False
        storage.close()

    def test_list_jobs_filters(self, db):
        storage.upsert_job(_job())
        storage.upsert_job(_job(title="Unreal Developer", language="en"))
        assert len(storage.list_jobs()) == 2
        assert len(storage.list_jobs(language="en")) == 1
        with pytest.raises(ValueError):
            storage.list_jobs(evil="1; DROP TABLE jobs")


class TestVolllaufHelpers:
    def _profile(self):
        pid = storage.create_profile("P", {"skills": ["Unity"]}, is_default=True)
        storage.save_criteria(pid, [{"key": "role_fit", "label": "Rolle",
                                     "weight": 5, "sort": 0}])
        return pid

    def test_list_feedback_with_titles_joins_jobs(self, db):
        pid = self._profile()
        fp = storage.upsert_job(_job(title="Feedback Job"))
        storage.add_feedback(pid, fp, "up")
        assert storage.list_feedback_with_titles(pid) == [
            {"vote": "up", "title": "Feedback Job"}]

    def test_set_sources_replaces_sources(self, db):
        fp = storage.upsert_job(_job())
        new_sources = [{"portal": "indeed",
                        "url": "https://de.indeed.com/viewjob?jk=x",
                        "found_at": "2026-07-11"}]
        storage.set_sources(fp, new_sources)
        assert storage.get_job(fp).sources == new_sources

    def test_delete_job_removes_scores_and_feedback(self, db):
        pid = self._profile()
        fp = storage.upsert_job(_job())
        storage.upsert_job_score(pid, fp, 50, "ok", "Vielleicht", {})
        storage.add_feedback(pid, fp, "down")
        storage.delete_job(fp)
        assert storage.get_job(fp) is None
        assert storage.get_job_score(pid, fp) is None
        assert storage.list_feedback(pid) == []


class TestLearnReminder:
    def _profile(self):
        return storage.create_profile("Member-Profil", {"no_gos": []})

    def test_never_learned_counts_all_votes(self, db):
        pid = self._profile()
        for i in range(3):
            fp = storage.upsert_job(_job(title=f"Job {i}"))
            storage.add_feedback(pid, fp, "up")
        assert storage.learn_reminder_status(pid) == {"new_votes": 3, "due": False}

    def test_due_once_threshold_reached(self, db):
        pid = self._profile()
        for i in range(storage._LEARN_REMINDER_THRESHOLD):
            fp = storage.upsert_job(_job(title=f"Job {i}"))
            storage.add_feedback(pid, fp, "up")
        assert storage.learn_reminder_status(pid)["due"] is True

    def test_touch_resets_counter(self, db):
        pid = self._profile()
        fp = storage.upsert_job(_job())
        storage.add_feedback(pid, fp, "up")
        storage.touch_learn_reminder(pid)
        assert storage.learn_reminder_status(pid) == {"new_votes": 0, "due": False}

    def test_votes_after_touch_count_again(self, db):
        pid = self._profile()
        storage.touch_learn_reminder(pid)
        conn = storage._require_conn()
        conn.execute(
            "UPDATE profiles SET last_learn_reminder_at = '2020-01-01T00:00:00' WHERE id = ?",
            (pid,))
        conn.commit()
        fp = storage.upsert_job(_job())
        storage.add_feedback(pid, fp, "up")
        assert storage.learn_reminder_status(pid) == {"new_votes": 1, "due": False}


class TestRawJobs:
    def test_insert_raw_job_creates_pending_row(self, db):
        fp = storage.insert_raw_job("https://indeed.test/raw1", "indeed",
                                    "Roher Anzeigentext", "2026-07-12")
        assert fp.startswith("url:")
        jobs = storage.list_jobs()
        assert len(jobs) == 1
        assert jobs[0].title == "" and jobs[0].company == ""
        assert jobs[0].sources == [{"portal": "indeed", "url": "https://indeed.test/raw1",
                                    "found_at": "2026-07-12"}]

    def test_insert_raw_job_dedups_same_url(self, db):
        storage.insert_raw_job("https://indeed.test/raw1", "indeed", "Text",
                               "2026-07-12")
        fp2 = storage.insert_raw_job("https://indeed.test/raw1", "indeed", "Text",
                                     "2026-07-13")
        assert len(storage.list_jobs()) == 1
        assert storage.list_pending_extraction()[0]["fingerprint"] == fp2

    def test_insert_raw_job_stores_role_and_neighbor_flag(self, db):
        storage.insert_raw_job("https://indeed.test/raw1", "indeed", "Text",
                               "2026-07-12", role="unity_games", is_neighbor=True)
        job = storage.list_jobs()[0]
        assert job.role == "unity_games"
        assert job.is_neighbor is True

    def test_list_pending_extraction_returns_pending_only(self, db):
        storage.insert_raw_job("https://a.test/1", "indeed", "Text A", "2026-07-12")
        storage.upsert_job(_job())  # bereits extrahiert
        pending = storage.list_pending_extraction()
        assert len(pending) == 1
        assert pending[0]["raw_text"] == "Text A"
        assert pending[0]["portal"] == "indeed"
        assert pending[0]["url"] == "https://a.test/1"

    def test_list_pending_extraction_respects_limit(self, db):
        for i in range(3):
            storage.insert_raw_job(f"https://a.test/{i}", "indeed", "T", "2026-07-12")
        assert len(storage.list_pending_extraction(limit=2)) == 2

    def test_apply_extraction_promotes_raw_row(self, db):
        raw_fp = storage.insert_raw_job("https://a.test/1", "indeed", "Text",
                                        "2026-07-12", role="unity_games")
        job = Job(title="Unity Developer", company="ACME", location="Hamburg",
                  first_seen="2026-07-12", last_seen="2026-07-12")
        new_fp = storage.apply_extraction(raw_fp, job)
        assert new_fp != raw_fp
        assert storage.get_job(raw_fp) is None
        loaded = storage.get_job(new_fp)
        assert loaded.title == "Unity Developer"
        assert loaded.role == "unity_games"  # aus Raw-Zeile erhalten
        assert loaded.sources == [{"portal": "indeed", "url": "https://a.test/1",
                                   "found_at": "2026-07-12"}]
        assert storage.list_pending_extraction() == []

    def test_apply_extraction_merges_into_existing_duplicate(self, db):
        # Gleicher Job über 2 Portale gefunden, bevor einer extrahiert wurde.
        raw_fp = storage.insert_raw_job("https://stepstone.test/1", "stepstone",
                                        "Text", "2026-07-12")
        existing_fp = storage.upsert_job(_job(
            sources=[{"portal": "indeed", "url": "https://indeed.test/1",
                     "found_at": "2026-07-11"}]))
        job = Job(title=_job().title, company=_job().company, location=_job().location,
                  first_seen="2026-07-12", last_seen="2026-07-12")
        assert job.fingerprint == existing_fp
        new_fp = storage.apply_extraction(raw_fp, job)
        assert new_fp == existing_fp
        assert storage.get_job(raw_fp) is None
        merged = storage.get_job(existing_fp)
        urls = {s["url"] for s in merged.sources}
        assert urls == {"https://indeed.test/1", "https://stepstone.test/1"}

    def test_apply_extraction_sets_is_ausland_for_foreign_location(self, db):
        pid = storage.create_profile("Testi", {}, is_default=True)
        raw_fp = storage.insert_raw_job("https://a.test/1", "indeed", "Text", "2026-07-12")
        job = Job(title="Remote Dev", company="ACME", location="New York",
                  first_seen="2026-07-12", last_seen="2026-07-12")
        storage.apply_extraction(raw_fp, job)
        entries = storage.list_jobs_with_scores(pid)
        assert entries[0]["is_ausland"] is True

    def test_list_jobs_with_scores_excludes_pending_extraction(self, db):
        pid = storage.create_profile("Testi", {}, is_default=True)
        storage.insert_raw_job("https://a.test/1", "indeed", "Text", "2026-07-12")
        storage.upsert_job(_job())
        entries = storage.list_jobs_with_scores(pid)
        assert len(entries) == 1
        assert entries[0]["job"].title != ""
