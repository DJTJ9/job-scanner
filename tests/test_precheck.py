"""Tests für precheck_portal() — Firecrawl-freier Kompatibilitäts-Check."""
from unittest.mock import patch

from jobscanner import precheck


def test_render_failure_is_incompatible():
    with patch("jobscanner.precheck.browser.render", return_value=None):
        result = precheck.precheck_portal("https://foo.de")
    assert result == {"rendered": False, "blocked": None, "structured": None,
                      "compatible": False, "reason": "Playwright konnte die Seite nicht laden"}


def test_cloudflare_block_marker_is_incompatible():
    html = "<html><body>Checking your browser before accessing foo.de. Cloudflare Ray ID.</body></html>"
    with patch("jobscanner.precheck.browser.render", return_value=html):
        result = precheck.precheck_portal("https://foo.de")
    assert result["rendered"] is True
    assert result["blocked"] is True
    assert result["compatible"] is False


def test_short_text_counts_as_blocked():
    html = "<html><body>Hi</body></html>"
    with patch("jobscanner.precheck.browser.render", return_value=html):
        result = precheck.precheck_portal("https://foo.de")
    assert result["blocked"] is True
    assert result["compatible"] is False


def test_structured_job_page_is_compatible():
    html = ("<html><body>" + "x" * 250 +
           "<h2>Ihre Aufgaben</h2><p>...</p><h2>Ihr Profil</h2><p>...</p>"
           "<h2>Wir bieten</h2><p>Vollzeit, Anforderungen erfüllt.</p>"
           "<a href='#'>Jetzt bewerben</a></body></html>")
    with patch("jobscanner.precheck.browser.render", return_value=html):
        result = precheck.precheck_portal("https://foo.de")
    assert result["rendered"] is True
    assert result["blocked"] is False
    assert result["structured"] is True
    assert result["compatible"] is True
    assert result["keyword_hits"] >= 2


def test_rendered_but_no_keywords_is_not_structured():
    html = "<html><body>" + ("Lorem ipsum dolor sit amet. " * 20) + "</body></html>"
    with patch("jobscanner.precheck.browser.render", return_value=html):
        result = precheck.precheck_portal("https://foo.de")
    assert result["blocked"] is False
    assert result["structured"] is False
    assert result["compatible"] is False
