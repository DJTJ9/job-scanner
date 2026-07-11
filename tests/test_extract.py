"""Tests für Extraktion — Playwright-Render und Groq-Client gemockt, kein Live-Call."""
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

HTML = ("<html><body><nav>Menu</nav>"
       "<h1>Unity Developer (m/w/d)</h1><p>ACME GmbH sucht dich.</p>"
       "<footer>Impressum</footer></body></html>")


def _groq_response(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=json.dumps(payload)))]
    return resp


class TestScrapeJob:
    def test_renders_cleans_and_extracts(self):
        with patch("jobscanner.extract.browser.render", return_value=HTML), \
             patch("jobscanner.extract.Groq") as MockGroq:
            MockGroq.return_value.chat.completions.create.return_value = _groq_response(RAW)
            raw = scrape_job("https://example.com/job/1")
        assert raw == RAW

    def test_render_failure_returns_none(self):
        with patch("jobscanner.extract.browser.render", return_value=None):
            assert scrape_job("https://example.com/x") is None

    def test_groq_bad_json_returns_none(self):
        with patch("jobscanner.extract.browser.render", return_value=HTML), \
             patch("jobscanner.extract.Groq") as MockGroq:
            resp = MagicMock()
            resp.choices = [MagicMock(message=MagicMock(content="not json"))]
            MockGroq.return_value.chat.completions.create.return_value = resp
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
