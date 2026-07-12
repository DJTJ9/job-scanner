"""Tests für Extraktion — Playwright-Fetch gemockt, kein Groq mehr im Pfad."""
from unittest.mock import patch

from jobscanner.extract import clean_api_text, fetch_raw_text, to_job

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


class TestFetchRawText:
    def test_fetches_and_cleans_html(self):
        with patch("jobscanner.extract.browser.fetch", return_value=HTML) as fetch:
            text = fetch_raw_text("https://example.com/job/1")
        assert "Unity Developer (m/w/d)" in text
        assert "Menu" not in text and "Impressum" not in text
        assert fetch.call_args.kwargs["method"] == "playwright"
        assert fetch.call_args.kwargs["failover"] is False

    def test_fetch_failure_returns_none(self):
        with patch("jobscanner.extract.browser.fetch", return_value=None):
            assert fetch_raw_text("https://example.com/x") is None

    def test_passes_fetch_method_and_failover(self):
        with patch("jobscanner.extract.browser.fetch", return_value=None) as fetch:
            fetch_raw_text("https://x.de/j/1", fetch_method="firecrawl", failover=True)
        assert fetch.call_args.kwargs["method"] == "firecrawl"
        assert fetch.call_args.kwargs["failover"] is True


class TestCleanApiText:
    def test_truncates_and_strips(self):
        assert clean_api_text("  Hallo Welt  ") == "Hallo Welt"

    def test_empty_text_stays_empty(self):
        assert clean_api_text("") == ""


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

    def test_tolerates_nested_dict_fields_from_llm(self):
        # Live-Volllauf 2026-07-12: LLM lieferte company als Objekt → .strip()-Crash
        raw = {"title": {"name": "Unity Dev"}, "company": {"name": "ACME GmbH"},
               "location": {"city": "Essen"}, "salary": {"min": 50000}}
        job = to_job(raw, "indeed", "u", "2026-07-12")
        assert job.title == "Unity Dev"
        assert job.company == "ACME GmbH"
        assert job.location == ""  # dict ohne name-Key → leer, kein Crash
        assert job.salary_text == ""

    def test_rejects_dict_fields_without_name(self):
        raw = {"title": {"x": 1}, "company": "ACME"}
        assert to_job(raw, "indeed", "u", "2026-07-12") is None
