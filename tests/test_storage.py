"""Tests für models.fingerprint + storage-Schicht (CRUD, Upsert)."""
import pytest

from jobscanner.models import Job, make_fingerprint, match_key


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


class TestMatchKey:
    def test_city_token_ignores_country_and_plz(self):
        assert match_key("ACME", "Unity Developer", "Berlin") == \
            match_key("ACME", "Unity Developer", "Berlin, 10115 DE")

    def test_city_token_distinguishes_cities(self):
        assert match_key("ACME", "Unity Developer", "Berlin") != \
            match_key("ACME", "Unity Developer", "München")

    def test_empty_location_yields_empty_city(self):
        assert match_key("ACME", "Unity Developer", "") == \
            match_key("ACME", "Unity Developer", "Remote")

    def test_drops_gender_marker_tokens(self):
        assert match_key("ACME", "Unity Developer (m/w/d)", "Berlin") == \
            match_key("ACME", "Unity Developer", "Berlin")

    def test_gender_marker_variants_collapse(self):
        assert match_key("ACME", "Unity Developer (f/m/x)", "Berlin") == \
            match_key("ACME", "Unity Developer (w/m/d)", "Berlin")

    def test_normalizes_seniority_abbrev(self):
        assert match_key("ACME", "Sr. Unity Developer", "Berlin") == \
            match_key("ACME", "Senior Unity Developer", "Berlin")

    def test_reuses_company_canonicalization(self):
        assert match_key("ACME GmbH", "Unity Developer", "Berlin") == \
            match_key("ACME", "Unity Developer", "Berlin")

    def test_different_role_differs(self):
        assert match_key("ACME", "Unity Developer", "Berlin") != \
            match_key("ACME", "Unreal Developer", "Berlin")


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

    def test_apply_extraction_merges_near_dup_by_match_key(self, db):
        pid = storage.create_profile("Testi", {}, is_default=True)
        # Survivor: bereits extrahiert, abweichende Location-Schreibweise + Gender-Marker im Titel.
        survivor_fp = storage.apply_extraction(
            storage.insert_raw_job("https://stepstone.test/1", "stepstone", "T", "2026-07-12"),
            Job(title="Unity Developer (m/w/d)", company="ACME GmbH",
                location="Berlin, 10115 DE", first_seen="2026-07-12", last_seen="2026-07-12"))
        # Near-Dup über anderes Portal: andere Location-/Titel-Schreibweise, gleiche Firma+Rolle+Stadt.
        raw_fp = storage.insert_raw_job("https://indeed.test/2", "indeed", "T", "2026-07-12")
        near = Job(title="Unity Developer", company="ACME",
                   location="Berlin", first_seen="2026-07-12", last_seen="2026-07-12")
        assert near.fingerprint != survivor_fp          # Content-Fingerprint würde NICHT matchen
        result_fp = storage.apply_extraction(raw_fp, near)

        assert result_fp == survivor_fp                 # Survivor behält Fingerprint
        assert storage.get_job(raw_fp) is None          # Near-Dup-Zeile gelöscht
        merged = storage.get_job(survivor_fp)
        urls = {s["url"] for s in merged.sources}
        assert urls == {"https://stepstone.test/1", "https://indeed.test/2"}
        # Nur EIN Scoring-Kandidat statt zwei.
        assert len(storage.list_unscored_extracted()) == 1

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


class TestRetroMerge:
    def test_retro_merge_consolidates_and_rehangs_fks(self, db):
        conn = storage._require_conn()
        pid = storage.create_profile("Testi", {}, is_default=True)
        # Zwei Bestands-Dups: gleiche Firma+Rolle+Stadt, abweichende Schreibweise → gleicher match_key,
        # unterschiedliche Fingerprints. Survivor (mit Score) + Loser (ohne Score, aber mit Favorit).
        survivor = Job(title="Unity Developer", company="ACME", location="Berlin",
                       first_seen="2026-07-01", last_seen="2026-07-01",
                       sources=[{"portal": "stepstone", "url": "https://s.test/1"}])
        loser = Job(title="Unity Developer (m/w/d)", company="ACME GmbH",
                    location="Berlin, 10115 DE", first_seen="2026-07-05", last_seen="2026-07-05",
                    sources=[{"portal": "indeed", "url": "https://i.test/2"}])
        survivor_fp = storage.upsert_job(survivor)
        loser_fp = storage.upsert_job(loser)
        assert survivor_fp != loser_fp
        # Survivor hat einen Score; Loser einen Favoriten + Feedback (müssen umgehängt werden).
        storage.upsert_job_score(pid, survivor_fp, 80, "gut", "Pass", {})
        storage.toggle_favorite(pid, loser_fp)
        storage.add_feedback(pid, loser_fp, "up")

        storage._retro_merge_by_match_key(conn)

        assert storage.get_job(loser_fp) is None            # Loser-Zeile weg
        merged = storage.get_job(survivor_fp)
        assert merged is not None                           # Survivor bleibt
        urls = {s["url"] for s in merged.sources}
        assert urls == {"https://s.test/1", "https://i.test/2"}
        assert storage.get_job_score(pid, survivor_fp)["score"] == 80  # Score erhalten
        # Favorit + Feedback auf Survivor umgehängt.
        assert conn.execute(
            "SELECT COUNT(*) FROM favorites WHERE profile_id=? AND fingerprint=?",
            (pid, survivor_fp)).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM favorites WHERE fingerprint=?", (loser_fp,)).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM feedback WHERE profile_id=? AND fingerprint=?",
            (pid, survivor_fp)).fetchone()[0] == 1

    def test_retro_merge_survivor_collision_keeps_survivor(self, db):
        conn = storage._require_conn()
        pid = storage.create_profile("Testi", {}, is_default=True)
        survivor_fp = storage.upsert_job(Job(title="Unity Developer", company="ACME",
                                             location="Berlin", first_seen="2026-07-01"))
        loser_fp = storage.upsert_job(Job(title="Unity Developer (m/w/d)", company="ACME GmbH",
                                          location="Berlin, DE", first_seen="2026-07-05"))
        # BEIDE haben einen Favoriten desselben Profils → (profile_id, fingerprint)-Kollision beim Umhang.
        storage.toggle_favorite(pid, survivor_fp)
        storage.toggle_favorite(pid, loser_fp)

        storage._retro_merge_by_match_key(conn)

        # Genau ein Favorit übrig, auf dem Survivor; kein UNIQUE-Fehler.
        assert conn.execute(
            "SELECT COUNT(*) FROM favorites WHERE fingerprint=?", (survivor_fp,)).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM favorites WHERE fingerprint=?", (loser_fp,)).fetchone()[0] == 0


class TestFirecrawlMemberKey:
    def test_set_get_clear_key(self, db):
        uid = storage.create_user("fc@test.de", "pw", role="member")
        assert storage.get_firecrawl_key_enc(uid) is None
        storage.set_firecrawl_key(uid, "enc-token-abc")
        assert storage.get_firecrawl_key_enc(uid) == "enc-token-abc"
        storage.clear_firecrawl_key(uid)
        assert storage.get_firecrawl_key_enc(uid) is None

    def test_custom_portal_failover_default_false_and_setter(self, db):
        uid = storage.create_user("p@test.de", "pw", role="member")
        pid = storage.create_custom_portal("https://foo.de", "career_page", uid)
        assert storage.get_custom_portal(pid)["firecrawl_failover"] is False
        storage.set_firecrawl_failover(pid, True)
        assert storage.get_custom_portal(pid)["firecrawl_failover"] is True

    def test_init_db_adds_columns_to_pre_firecrawl_schema(self, tmp_path):
        import sqlite3
        db_path = tmp_path / "old.db"
        conn = sqlite3.connect(db_path)
        conn.executescript(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, "
            "pw_hash TEXT NOT NULL, salt TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'member', "
            "api_token_hash TEXT, created_at TEXT);")
        conn.commit()
        conn.close()
        storage.init_db(db_path)  # darf nicht crashen, Spalte additiv ergaenzt
        cols = {r["name"] for r in storage._require_conn().execute("PRAGMA table_info(users)")}
        assert "firecrawl_key_enc" in cols


class TestScoreQueueSperrtAusland:
    @pytest.fixture(autouse=True)
    def db(self, tmp_path):
        from jobscanner import storage
        storage.init_db(tmp_path / "jobs.db")
        yield
        storage.close()

    def test_list_unscored_extracted_skips_ausland(self):
        from jobscanner import storage
        from jobscanner.models import Job
        storage.upsert_job(Job(title="DE Job", company="A", location="Hamburg",
                               first_seen="2026-08-01"))
        storage.upsert_job(Job(title="US Job", company="B", location="Austin, TX",
                               first_seen="2026-08-01"))
        titel = [j["title"] for j in storage.list_unscored_extracted()]
        assert titel == ["DE Job"]

    def test_list_unscored_for_profiles_skips_ausland(self):
        from jobscanner import storage
        from jobscanner.models import Job
        pid = storage.create_profile("Testi", {})
        storage.upsert_job(Job(title="DE Job", company="A", location="Hamburg",
                               first_seen="2026-08-01"))
        storage.upsert_job(Job(title="US Job", company="B", location="Austin, TX",
                               first_seen="2026-08-01"))
        titel = [j["title"] for j in storage.list_unscored_for_profiles([pid])]
        assert titel == ["DE Job"]
