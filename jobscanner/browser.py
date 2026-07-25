"""Fetch-Layer: Playwright-Render + Firecrawl-CLI-Dispatcher.

Firecrawl nur für nachweislich geblockte Pfade (StepStone-Details, Indeed) und
als optionaler 1x-Failover — kein Stealth/Evasion (Policy). Nur `scrape -f html`.
"""
from __future__ import annotations

import ipaddress
import re
import socket
import subprocess
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from jobscanner import config

_TIMEOUT_MS = 30000
_FC_TIMEOUT_S = 60
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")  # CLI färbt auch ohne TTY (live verifiziert 2026-07-11)
_credits_ok: bool | None = None  # Prozess-Cache — 1 Status-Call pro Lauf
FC_COST_SCRAPE = 1
FC_COST_SEARCH = 5  # Indeed-Suche: Firecrawl eskaliert intern auf Stealth (Learning 2026-07-11)
_credits_spent = 0


def reset_credits() -> None:
    global _credits_spent
    _credits_spent = 0


def credits_spent() -> int:
    return _credits_spent


def credits_remaining() -> int | None:
    """Echter Credit-Stand via `firecrawl --status` — ungecacht, für Vorher/Nachher-Messung."""
    try:
        res = subprocess.run(["firecrawl", "--status"],
                             capture_output=True, text=True, timeout=30)
    except (subprocess.TimeoutExpired, OSError):
        return None
    m = re.search(r"Credits:\s*([\d,.]+)\s*/", _ANSI_RE.sub("", res.stdout))
    return int(re.sub(r"[,.]", "", m.group(1))) if m else None


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


def render(url: str) -> str | None:
    try:
        with sync_playwright() as p:
            browser_obj = p.chromium.launch()
            page = browser_obj.new_page()
            def _guard(route, request):
                if _reject_ssrf(request.url) is not None:
                    route.abort()
                else:
                    route.continue_()
            page.route("**/*", _guard)
            page.goto(url, timeout=_TIMEOUT_MS, wait_until="domcontentloaded")
            html = page.content()
            browser_obj.close()
            return html
    except Exception:
        return None


def _firecrawl_scrape(url: str, cost: int = FC_COST_SCRAPE) -> str | None:
    global _credits_spent
    if _credits_spent + cost > config.firecrawl_budget():
        return None
    _credits_spent += cost
    try:
        res = subprocess.run(["firecrawl", "scrape", url, "-f", "html"],
                             capture_output=True, text=True, timeout=_FC_TIMEOUT_S)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if res.returncode != 0:
        return None
    return res.stdout.strip() or None


def firecrawl_credits_ok() -> bool:
    global _credits_ok
    if _credits_ok is None:
        rem = credits_remaining()
        _credits_ok = bool(rem and rem > 0)
    return _credits_ok


def fetch(url: str, method: str = "playwright", failover: bool = False,
          cost: int = FC_COST_SCRAPE) -> str | None:
    if method == "firecrawl":
        return _firecrawl_scrape(url, cost=cost) if firecrawl_credits_ok() else None
    html = render(url)
    if html is None and failover and firecrawl_credits_ok():
        return _firecrawl_scrape(url, cost=cost)
    return html
