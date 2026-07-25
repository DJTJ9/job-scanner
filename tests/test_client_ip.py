"""Tests für client_ip() — echte Client-IP aus X-Forwarded-For hinter Caddy."""
from jobscanner.web.app import client_ip


class _Client:
    def __init__(self, host):
        self.host = host


class _Req:
    def __init__(self, xff=None, host="127.0.0.1"):
        self.headers = {"x-forwarded-for": xff} if xff is not None else {}
        self.client = _Client(host) if host is not None else None


def test_single_xff_entry_is_used():
    assert client_ip(_Req(xff="203.0.113.7")) == "203.0.113.7"


def test_rightmost_entry_wins_over_left():
    # Caddy hängt die echte Peer-IP rechts an; linke Werte sind client-gesetzt.
    assert client_ip(_Req(xff="1.2.3.4, 203.0.113.7")) == "203.0.113.7"


def test_spoofed_left_entry_is_ignored():
    # Angreifer setzt selbst einen linken XFF-Wert — darf den Rate-Key nicht bestimmen.
    assert client_ip(_Req(xff="9.9.9.9, 203.0.113.7")) == "203.0.113.7"


def test_whitespace_is_stripped():
    assert client_ip(_Req(xff="1.2.3.4,   203.0.113.7  ")) == "203.0.113.7"


def test_no_header_falls_back_to_client_host():
    assert client_ip(_Req(xff=None, host="198.51.100.9")) == "198.51.100.9"


def test_no_header_no_client_is_unknown():
    assert client_ip(_Req(xff=None, host=None)) == "unknown"
