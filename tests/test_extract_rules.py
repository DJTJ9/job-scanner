"""Tests für die LLM-freie Regel-Extraktion (extract_rules.to_job)."""
from jobscanner import extract_rules

_TODAY = "2026-07-29"


def test_to_job_builds_from_listing_metadata():
    listing = {
        "url": "https://x.de/1", "portal": "stepstone",
        "title": "Junior Python Developer",
        "company": "Acme GmbH", "location": "Berlin",
        "raw_text": "Wir suchen dich.\nRemote möglich.\nUnbefristet in Vollzeit.\nPython, SQL.",
    }
    job = extract_rules.to_job(listing, _TODAY)
    assert job is not None
    assert job.title == "Junior Python Developer"
    assert job.company == "Acme GmbH"
    assert job.location == "Berlin"
    assert job.remote_flag == "remote"
    assert job.employment_type == "Vollzeit"
    assert job.requirements
    assert any("Python" in r for r in job.requirements)


def test_to_job_none_without_company():
    listing = {"url": "https://x.de/2", "portal": "indeed",
               "title": "Developer", "company": "", "raw_text": "Text."}
    assert extract_rules.to_job(listing, _TODAY) is None


def test_to_job_none_without_title():
    listing = {"url": "https://x.de/3", "portal": "indeed",
               "title": "", "company": "Acme", "raw_text": "Text."}
    assert extract_rules.to_job(listing, _TODAY) is None


def test_remote_flag_onsite_default_when_no_signal():
    listing = {"url": "https://x.de/4", "portal": "indeed", "title": "Dev",
               "company": "Acme", "raw_text": "Reine Bürotätigkeit vor Ort."}
    job = extract_rules.to_job(listing, _TODAY)
    assert job.remote_flag == "onsite"
