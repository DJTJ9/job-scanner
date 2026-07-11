"""Fetch-Layer: Playwright-Render + Firecrawl-CLI-Dispatcher.

Firecrawl nur für nachweislich geblockte Pfade (StepStone-Details, Indeed) und
als optionaler 1x-Failover — kein Stealth/Evasion (Policy). Nur `scrape -f html`.
"""
from __future__ import annotations

import re
import subprocess

from playwright.sync_api import sync_playwright

_TIMEOUT_MS = 30000
_FC_TIMEOUT_S = 60
_credits_ok: bool | None = None  # Prozess-Cache — 1 Status-Call pro Lauf


def render(url: str) -> str | None:
    try:
        with sync_playwright() as p:
            browser_obj = p.chromium.launch()
            page = browser_obj.new_page()
            page.goto(url, timeout=_TIMEOUT_MS, wait_until="domcontentloaded")
            html = page.content()
            browser_obj.close()
            return html
    except Exception:
        return None


def _firecrawl_scrape(url: str) -> str | None:
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
        try:
            res = subprocess.run(["firecrawl", "--status"],
                                 capture_output=True, text=True, timeout=30)
            m = re.search(r"Credits:\s*([\d,.]+)\s*/", res.stdout)
            _credits_ok = bool(m and int(re.sub(r"[,.]", "", m.group(1))) > 0)
        except (subprocess.TimeoutExpired, OSError):
            _credits_ok = False
    return _credits_ok


def fetch(url: str, method: str = "playwright", failover: bool = False) -> str | None:
    if method == "firecrawl":
        return _firecrawl_scrape(url) if firecrawl_credits_ok() else None
    html = render(url)
    if html is None and failover and firecrawl_credits_ok():
        return _firecrawl_scrape(url)
    return html
