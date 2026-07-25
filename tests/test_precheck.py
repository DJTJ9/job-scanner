"""Tests für precheck_portal() — Firecrawl-freier Kompatibilitäts-Check."""
from unittest.mock import MagicMock, patch

import pytest

from jobscanner import precheck


@pytest.fixture(autouse=True)
def _public_dns(monkeypatch):
    # Hostnamen (foo.de etc.) hermetisch auf eine öffentliche IP auflösen,
    # damit kein echtes DNS im Test nötig ist. Literal-IP-Tests umgehen dies.
    monkeypatch.setattr("jobscanner.browser.socket.getaddrinfo",
                        lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))])


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


# --- SSRF-Guard: precheck_portal darf browser.render() nur für externe http/https-URLs aufrufen ---

def test_file_scheme_blocked_before_render():
    render = MagicMock()
    with patch("jobscanner.precheck.browser.render", render):
        result = precheck.precheck_portal("file:///etc/passwd")
    assert result["compatible"] is False
    assert result["rendered"] is False
    assert "http" in result["reason"].lower()
    render.assert_not_called()


def test_loopback_ip_blocked_before_render():
    render = MagicMock()
    with patch("jobscanner.precheck.browser.render", render):
        result = precheck.precheck_portal("http://127.0.0.1:8010/dashboard")
    assert result["compatible"] is False
    assert result["rendered"] is False
    render.assert_not_called()


def test_link_local_metadata_blocked_before_render():
    render = MagicMock()
    with patch("jobscanner.precheck.browser.render", render):
        result = precheck.precheck_portal("http://169.254.169.254/latest/meta-data/")
    assert result["compatible"] is False
    render.assert_not_called()


def test_private_ip_blocked_before_render():
    render = MagicMock()
    with patch("jobscanner.precheck.browser.render", render):
        result = precheck.precheck_portal("http://10.0.0.5/")
    assert result["compatible"] is False
    render.assert_not_called()


def test_hostname_resolving_to_private_ip_blocked(monkeypatch):
    # DNS-Rebinding-Stil: öffentlich aussehender Host, der auf eine interne IP zeigt.
    monkeypatch.setattr("jobscanner.browser.socket.getaddrinfo",
                        lambda *a, **k: [(2, 1, 6, "", ("10.0.0.5", 0))])
    render = MagicMock()
    with patch("jobscanner.precheck.browser.render", render):
        result = precheck.precheck_portal("https://evil.example.com/")
    assert result["compatible"] is False
    render.assert_not_called()


def test_ipv6_mapped_ipv4_loopback_blocked():
    render = MagicMock()
    with patch("jobscanner.precheck.browser.render", render):
        result = precheck.precheck_portal("http://[::ffff:127.0.0.1]/")
    assert result["compatible"] is False
    render.assert_not_called()


def test_ipv6_mapped_metadata_blocked():
    render = MagicMock()
    with patch("jobscanner.precheck.browser.render", render):
        result = precheck.precheck_portal("http://[::ffff:169.254.169.254]/")
    assert result["compatible"] is False
    render.assert_not_called()


def test_public_url_still_reaches_render():
    html = ("<html><body>" + "x" * 250 +
           "<h2>Ihre Aufgaben</h2><h2>Ihr Profil</h2><p>Vollzeit, Anforderungen.</p>"
           "<a>Jetzt bewerben</a></body></html>")
    with patch("jobscanner.precheck.browser.render", return_value=html) as render:
        result = precheck.precheck_portal("https://jobs.example.com/stelle")
    render.assert_called_once()
    assert result["rendered"] is True
