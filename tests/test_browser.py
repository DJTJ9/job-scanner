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


class TestFirecrawlScrape:
    def test_returns_stdout_html(self):
        res = MagicMock(returncode=0, stdout="<html>fc</html>\n")
        with patch("jobscanner.browser.subprocess.run", return_value=res):
            from jobscanner.browser import _firecrawl_scrape
            assert _firecrawl_scrape("https://example.com/x") == "<html>fc</html>"

    def test_returns_none_on_nonzero_exit(self):
        res = MagicMock(returncode=1, stdout="")
        with patch("jobscanner.browser.subprocess.run", return_value=res):
            from jobscanner.browser import _firecrawl_scrape
            assert _firecrawl_scrape("https://example.com/x") is None

    def test_returns_none_on_timeout(self):
        import subprocess as sp
        with patch("jobscanner.browser.subprocess.run", side_effect=sp.TimeoutExpired("firecrawl", 60)):
            from jobscanner.browser import _firecrawl_scrape
            assert _firecrawl_scrape("https://example.com/x") is None


class TestCreditsOk:
    def _status(self, text):
        return MagicMock(returncode=0, stdout=text)

    def test_true_when_credits_left(self):
        import jobscanner.browser as b
        b._credits_ok = None
        with patch("jobscanner.browser.subprocess.run", return_value=self._status("Credits: 2,847 / 3,000")):
            assert b.firecrawl_credits_ok() is True

    def test_true_on_live_ansi_output(self):
        # Echtes CLI-Format v1.16.2 (live verifiziert 2026-07-11): ANSI-Codes auch bei Pipe-Capture.
        live = ("  \x1b[38;5;208m\U0001f525 \x1b[1mfirecrawl\x1b[0m \x1b[2mcli\x1b[0m \x1b[2mv1.16.2\x1b[0m\n\n"
                "  \x1b[32m●\x1b[0m Authenticated \x1b[2mvia stored credentials\x1b[0m\n"
                "  \x1b[2mConcurrency:\x1b[0m 0/5 jobs \x1b[2m(parallel scrape limit)\x1b[0m\n"
                "  \x1b[2mCredits:\x1b[0m 5,000 / 5,000 \x1b[2m(100% left this cycle)\x1b[0m\n")
        import jobscanner.browser as b
        b._credits_ok = None
        with patch("jobscanner.browser.subprocess.run", return_value=self._status(live)):
            assert b.firecrawl_credits_ok() is True

    def test_false_when_zero(self):
        import jobscanner.browser as b
        b._credits_ok = None
        with patch("jobscanner.browser.subprocess.run", return_value=self._status("Credits: 0 / 1,000")):
            assert b.firecrawl_credits_ok() is False

    def test_cached_after_first_call(self):
        import jobscanner.browser as b
        b._credits_ok = None
        with patch("jobscanner.browser.subprocess.run", return_value=self._status("Credits: 5 / 1,000")) as run:
            b.firecrawl_credits_ok()
            b.firecrawl_credits_ok()
        assert run.call_count == 1


class TestCreditBudget:
    def setup_method(self):
        import jobscanner.browser as b
        b.reset_credits()

    def test_scrape_charges_one_credit(self):
        import jobscanner.browser as b
        res = MagicMock(returncode=0, stdout="<html>fc</html>")
        with patch("jobscanner.browser.subprocess.run", return_value=res):
            b._firecrawl_scrape("https://example.com/x")
        assert b.credits_spent() == 1

    def test_search_cost_charges_five(self):
        import jobscanner.browser as b
        res = MagicMock(returncode=0, stdout="<html>fc</html>")
        with patch("jobscanner.browser.subprocess.run", return_value=res):
            b._firecrawl_scrape("https://de.indeed.com/jobs?q=x", cost=b.FC_COST_SEARCH)
        assert b.credits_spent() == 5

    def test_charge_happens_even_on_failed_call(self):
        # Konservativ: Firecrawl kann serverseitig auch für Fehlversuche Credits ziehen.
        import jobscanner.browser as b
        res = MagicMock(returncode=1, stdout="")
        with patch("jobscanner.browser.subprocess.run", return_value=res):
            assert b._firecrawl_scrape("https://example.com/x") is None
        assert b.credits_spent() == 1

    def test_call_skipped_when_budget_exhausted(self, monkeypatch):
        monkeypatch.setenv("JOBSCANNER_FC_BUDGET", "3")
        import jobscanner.browser as b
        b.reset_credits()
        with patch("jobscanner.browser.subprocess.run") as run:
            assert b._firecrawl_scrape("https://example.com/x", cost=5) is None
        run.assert_not_called()
        assert b.credits_spent() == 0

    def test_fetch_passes_cost_to_firecrawl(self):
        import jobscanner.browser as b
        b._credits_ok = True
        res = MagicMock(returncode=0, stdout="<html>fc</html>")
        with patch("jobscanner.browser.subprocess.run", return_value=res):
            b.fetch("https://de.indeed.com/jobs?q=x", method="firecrawl",
                    cost=b.FC_COST_SEARCH)
        assert b.credits_spent() == 5


class TestCreditsRemaining:
    def test_parses_absolute_value(self):
        res = MagicMock(returncode=0, stdout="Credits: 4,980 / 5,000")
        with patch("jobscanner.browser.subprocess.run", return_value=res):
            from jobscanner import browser
            assert browser.credits_remaining() == 4980

    def test_none_on_timeout(self):
        import subprocess as sp
        with patch("jobscanner.browser.subprocess.run",
                   side_effect=sp.TimeoutExpired("firecrawl", 30)):
            from jobscanner import browser
            assert browser.credits_remaining() is None

    def test_none_when_no_credits_line(self):
        res = MagicMock(returncode=0, stdout="kein Match")
        with patch("jobscanner.browser.subprocess.run", return_value=res):
            from jobscanner import browser
            assert browser.credits_remaining() is None


class TestFetch:
    def test_playwright_default(self):
        import jobscanner.browser as b
        with patch("jobscanner.browser.render", return_value="<html>pw</html>") as render:
            assert b.fetch("https://example.com/x") == "<html>pw</html>"
        render.assert_called_once()

    def test_firecrawl_method_uses_subprocess(self):
        import jobscanner.browser as b
        b._credits_ok = True
        with patch("jobscanner.browser._firecrawl_scrape", return_value="<html>fc</html>") as fc, \
             patch("jobscanner.browser.render") as render:
            assert b.fetch("https://example.com/x", method="firecrawl") == "<html>fc</html>"
        render.assert_not_called()
        fc.assert_called_once()

    def test_firecrawl_method_skipped_without_credits(self):
        import jobscanner.browser as b
        b._credits_ok = False
        with patch("jobscanner.browser._firecrawl_scrape") as fc:
            assert b.fetch("https://example.com/x", method="firecrawl") is None
        fc.assert_not_called()

    def test_failover_on_playwright_failure(self):
        import jobscanner.browser as b
        b._credits_ok = True
        with patch("jobscanner.browser.render", return_value=None), \
             patch("jobscanner.browser._firecrawl_scrape", return_value="<html>fc</html>") as fc:
            assert b.fetch("https://example.com/x", failover=True) == "<html>fc</html>"
        fc.assert_called_once()

    def test_no_failover_by_default(self):
        import jobscanner.browser as b
        with patch("jobscanner.browser.render", return_value=None), \
             patch("jobscanner.browser._firecrawl_scrape") as fc:
            assert b.fetch("https://example.com/x") is None
        fc.assert_not_called()

    def test_failover_forwards_caller_cost(self):
        import jobscanner.browser as b
        b._credits_ok = True
        with patch("jobscanner.browser.render", return_value=None), \
             patch("jobscanner.browser._firecrawl_scrape", return_value="<html>fc</html>") as fc:
            assert b.fetch("https://example.com/x", failover=True,
                           cost=b.FC_COST_SEARCH) == "<html>fc</html>"
        fc.assert_called_once_with("https://example.com/x", cost=b.FC_COST_SEARCH)


from unittest.mock import patch, MagicMock

from jobscanner.browser import render, _reject_ssrf


class TestRejectSsrf:
    def test_blocks_file_scheme(self):
        assert _reject_ssrf("file:///etc/passwd") is not None

    def test_blocks_loopback_literal(self):
        assert _reject_ssrf("http://127.0.0.1/") is not None

    def test_blocks_metadata_literal(self):
        assert _reject_ssrf("http://169.254.169.254/latest/meta-data/") is not None

    def test_allows_public_host(self):
        with patch("jobscanner.browser.socket.getaddrinfo",
                   return_value=[(2, 1, 6, "", ("93.184.216.34", 0))]):
            assert _reject_ssrf("https://example.com/") is None


class TestRenderSsrfGuard:
    def _handler_from(self, cm):
        page = cm.__enter__.return_value.chromium.launch.return_value.new_page.return_value
        # page.route("**/*", _guard) — Handler ist das zweite Positional-Argument
        return page.route.call_args[0][1]

    def test_render_registers_route_guard(self):
        cm = _mock_playwright("<html>ok</html>")
        with patch("jobscanner.browser.sync_playwright", return_value=cm):
            render("https://example.com/")
        page = cm.__enter__.return_value.chromium.launch.return_value.new_page.return_value
        page.route.assert_called_once()
        assert page.route.call_args[0][0] == "**/*"

    def test_guard_aborts_private_redirect_hop(self):
        cm = _mock_playwright("<html>ok</html>")
        with patch("jobscanner.browser.sync_playwright", return_value=cm):
            render("https://example.com/")
        guard = self._handler_from(cm)
        route = MagicMock()
        req = MagicMock(url="http://169.254.169.254/latest/meta-data/")
        guard(route, req)
        route.abort.assert_called_once()
        route.continue_.assert_not_called()

    def test_guard_continues_global_request(self):
        cm = _mock_playwright("<html>ok</html>")
        with patch("jobscanner.browser.sync_playwright", return_value=cm):
            render("https://example.com/")
        guard = self._handler_from(cm)
        route = MagicMock()
        req = MagicMock(url="https://example.com/next")
        with patch("jobscanner.browser.socket.getaddrinfo",
                   return_value=[(2, 1, 6, "", ("93.184.216.34", 0))]):
            guard(route, req)
        route.continue_.assert_called_once()
        route.abort.assert_not_called()
