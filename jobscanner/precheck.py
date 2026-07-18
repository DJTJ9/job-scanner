"""Firecrawl-freier Kompatibilitäts-Check für Kandidaten-Portale (custom_portals).

Ruft NIE Firecrawl auf — genau das ist der Zweck des Tools (Kosten schon beim
Prüfen vermeiden, nicht erst beim laufenden Scan).
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from jobscanner import browser
from jobscanner.extract import _clean_text

_BLOCK_MARKERS = (
    "checking your browser", "cloudflare", "captcha", "access denied",
    "bitte aktivieren sie javascript", "enable javascript", "just a moment",
    "attention required",
)
_STRUCTURE_KEYWORDS = (
    "anforderungen", "aufgaben", "ihr profil", "wir bieten", "bewerbung",
    "vollzeit", "teilzeit", "requirements", "responsibilities", "apply now",
)
_MIN_STRUCTURE_HITS = 2
_MIN_TEXT_LEN = 200


def _reject_ssrf(url: str) -> str | None:
    """SSRF-Guard: nur externe http/https-Ziele erlauben. Gibt einen Grund
    zurück, wenn die URL geblockt werden muss, sonst None. Blockt file:// & Co.,
    IP-Literale und Hostnamen, die auf private/loopback/link-local/reservierte
    Adressen auflösen (inkl. Cloud-Metadata 169.254.169.254)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return "Nur http/https-URLs erlaubt"
    host = parsed.hostname
    if not host:
        return "Keine gültige Host-Angabe in der URL"
    try:
        ips = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror:
            return "Host nicht auflösbar"
        ips = [ipaddress.ip_address(info[4][0]) for info in infos]
    for ip in ips:
        # IPv4-mapped IPv6 (::ffff:127.0.0.1) auf die eingebettete v4 normalisieren,
        # damit der is_global-Check nicht am v6-Wrapper vorbeiläuft.
        if ip.version == 6 and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        # is_global schließt private/loopback/link-local/reserved/multicast/
        # unspecified/CGNAT in einem Prädikat ein — nur global-routbare Ziele erlaubt.
        if not ip.is_global:
            return "Interne/private Adresse nicht erlaubt"
    return None


def precheck_portal(url: str) -> dict:
    reason = _reject_ssrf(url)
    if reason is not None:
        return {"rendered": False, "blocked": None, "structured": None,
                "compatible": False, "reason": reason}
    html = browser.render(url)
    if html is None:
        return {"rendered": False, "blocked": None, "structured": None,
                "compatible": False, "reason": "Playwright konnte die Seite nicht laden"}
    text = _clean_text(html)
    norm = text.lower()
    blocked = any(marker in norm for marker in _BLOCK_MARKERS) or len(text) < _MIN_TEXT_LEN
    hits = sum(1 for kw in _STRUCTURE_KEYWORDS if kw in norm)
    structured = not blocked and hits >= _MIN_STRUCTURE_HITS
    return {"rendered": True, "blocked": blocked, "structured": structured,
            "compatible": not blocked and structured,
            "text_len": len(text), "keyword_hits": hits}
