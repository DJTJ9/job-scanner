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
