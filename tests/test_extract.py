"""Tests für Extraktion — subprocess gemockt."""
import json
from unittest.mock import patch, MagicMock

from jobscanner.extract import scrape_job, to_job

RAW = {
    "title": "Unity Developer (m/w/d)",
    "company": "ACME GmbH",
    "location": "Hamburg",
    "remote": "hybrid",
    "employment_type": "Vollzeit",
    "language": "de",
    "salary": "50.000–60.000 €",
    "requirements": ["Unity", "2 Jahre Erfahrung"],
    "tech_stack": ["Unity", "C#"],
}


class TestScrapeJob:
    def test_calls_firecrawl_with_schema_and_parses(self):
        # Echte Hülle (CLI 1.16.2, verifiziert 2026-07-10): "Scrape ID"-Zeile,
        # dann JSON mit Top-Level-Keys "json" (extrahierte Felder) + "metadata".
        payload = "Scrape ID: 019f4cab\n" + json.dumps(
            {"json": RAW, "metadata": {"title": "..."}})
        with patch("jobscanner.extract.subprocess.run",
                   return_value=MagicMock(returncode=0, stdout=payload, stderr="")) as run:
            raw = scrape_job("https://example.com/job/1")
        assert raw == RAW
        cmd = run.call_args[0][0]
        assert cmd[:2] == ["firecrawl", "scrape"]
        assert "--schema-file" in cmd and "json" in cmd

    def test_failed_scrape_returns_none(self):
        with patch("jobscanner.extract.subprocess.run",
                   return_value=MagicMock(returncode=1, stdout="", stderr="blocked")):
            assert scrape_job("https://example.com/x") is None


class TestToJob:
    def test_builds_valid_job(self):
        job = to_job(RAW, portal="stepstone",
                     url="https://example.com/job/1", today="2026-07-10")
        assert job.title == "Unity Developer (m/w/d)"
        assert job.remote_flag == "hybrid"
        assert job.salary_text == "50.000–60.000 €"
        assert job.sources == [{"portal": "stepstone",
                                "url": "https://example.com/job/1",
                                "found_at": "2026-07-10"}]
        assert job.first_seen == "2026-07-10" and job.last_seen == "2026-07-10"

    def test_rejects_missing_title_or_company(self):
        assert to_job({"company": "ACME"}, "indeed", "u", "2026-07-10") is None
        assert to_job({"title": "Dev"}, "indeed", "u", "2026-07-10") is None

    def test_optional_fields_default_cleanly(self):
        job = to_job({"title": "Dev", "company": "ACME"}, "indeed", "u", "2026-07-10")
        assert job.salary_text == "" and job.remote_flag == "unknown"
        assert job.requirements == [] and job.tech_stack == []
