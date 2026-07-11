"""Tests für Playwright-Wrapper — sync_playwright gemockt, kein echter Browser-Start."""
from unittest.mock import patch, MagicMock

from jobscanner.browser import render


def _mock_playwright(html: str = "", raise_error: bool = False) -> MagicMock:
    pw = MagicMock()
    if raise_error:
        pw.chromium.launch.side_effect = RuntimeError("boom")
    else:
        page = MagicMock()
        page.content.return_value = html
        browser_obj = MagicMock()
        browser_obj.new_page.return_value = page
        pw.chromium.launch.return_value = browser_obj
    cm = MagicMock()
    cm.__enter__.return_value = pw
    cm.__exit__.return_value = False
    return cm


class TestRender:
    def test_returns_page_html(self):
        cm = _mock_playwright("<html><body>Job</body></html>")
        with patch("jobscanner.browser.sync_playwright", return_value=cm):
            html = render("https://example.com/job/1")
        assert html == "<html><body>Job</body></html>"

    def test_returns_none_on_error(self):
        cm = _mock_playwright(raise_error=True)
        with patch("jobscanner.browser.sync_playwright", return_value=cm):
            assert render("https://example.com/x") is None
