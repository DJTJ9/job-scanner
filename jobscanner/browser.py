"""Playwright-Wrapper — rendert JS-lastige Seiten, ersetzt Firecrawls Scrape-Rendering."""
from __future__ import annotations

from playwright.sync_api import sync_playwright

_TIMEOUT_MS = 30000


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
