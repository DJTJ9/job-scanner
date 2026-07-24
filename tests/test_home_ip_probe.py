"""Tests für home_ip_probe.classify — rein netzfrei, kein Browser-Start."""
from home_ip_probe import classify


class TestStepStone:
    def test_http2_error_is_fail(self):
        assert classify("stepstone", 0, "net::ERR_HTTP2_PROTOCOL_ERROR", "") == "FAIL"

    def test_timeout_error_is_fail(self):
        assert classify("stepstone", 0, "Timeout 30000ms exceeded", "") == "FAIL"

    def test_loaded_content_is_pass(self):
        assert classify("stepstone", 200, None,
                        "<html>Softwareentwickler Vollzeit</html>") == "PASS"

    def test_empty_page_no_error_is_fail(self):
        assert classify("stepstone", 200, None, "<html></html>") == "FAIL"


class TestIndeed:
    def test_403_is_fail(self):
        assert classify("indeed", 403, None, "") == "FAIL"

    def test_turnstile_marker_is_fail(self):
        assert classify("indeed", 200, None,
                        "<html><title>Just a moment...</title></html>") == "FAIL"

    def test_listing_is_pass(self):
        assert classify("indeed", 200, None,
                        "<html>Softwareentwickler Jobs Bewerben</html>") == "PASS"

    def test_200_but_empty_is_fail(self):
        assert classify("indeed", 200, None, "<html></html>") == "FAIL"
