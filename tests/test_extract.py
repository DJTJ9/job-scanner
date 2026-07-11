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


class TestExtractFromText:
    def _groq_resp(self, payload: str):
        resp = MagicMock()
        resp.choices = [MagicMock(message=MagicMock(content=payload))]
        return resp

    def test_extracts_dict_from_plain_text(self):
        from jobscanner.extract import extract_from_text
        with patch("jobscanner.extract.Groq") as groq_cls:
            groq_cls.return_value.chat.completions.create.return_value = \
                self._groq_resp('{"title": "Junior Unity Developer", "company": "ACME"}')
            raw = extract_from_text("Junior Unity Developer\nACME GmbH\nHamburg\nUnity, C#")
        assert raw == {"title": "Junior Unity Developer", "company": "ACME"}

    def test_empty_text_returns_none(self):
        from jobscanner.extract import extract_from_text
        with patch("jobscanner.extract.Groq") as groq_cls:
            assert extract_from_text("   ") is None
        groq_cls.assert_not_called()


class TestScrapeJobRouting:
    def test_passes_fetch_method_and_failover(self):
        from jobscanner.extract import scrape_job
        with patch("jobscanner.extract.browser.fetch", return_value=None) as fetch:
            assert scrape_job("https://x.de/j/1", fetch_method="firecrawl", failover=True) is None
        assert fetch.call_args.kwargs["method"] == "firecrawl"
        assert fetch.call_args.kwargs["failover"] is True

    def test_default_method_playwright(self):
        from jobscanner.extract import scrape_job
        with patch("jobscanner.extract.browser.fetch", return_value=None) as fetch:
            scrape_job("https://x.de/j/1")
        assert fetch.call_args.kwargs["method"] == "playwright"


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
