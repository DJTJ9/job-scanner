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

    def test_list_jobs_filters(self, db):
        storage.upsert_job(_job())
        storage.upsert_job(_job(title="Unreal Developer", language="en"))
        assert len(storage.list_jobs()) == 2
        assert len(storage.list_jobs(language="en")) == 1
        with pytest.raises(ValueError):
            storage.list_jobs(evil="1; DROP TABLE jobs")
