#!/usr/bin/env python3
"""Home-IP-Gate-Test: prüft vom Raspberry Pi (Home-IP) aus, ob StepStone + Indeed
laden, an denen die Hetzner-Datacenter-IP scheitert (StepStone ERR_HTTP2_PROTOCOL_ERROR
auf Detailseiten, Indeed Cloudflare-Turnstile-403). Standalone — kein Reverse-Tunnel,
keine Server-Verbindung, keine job-scanner-Env, nur Playwright. Exit 0 nur wenn Indeed
UND StepStone grün, sonst 1. Setup + Ausführung: siehe HOME_IP_PROBE.md.
"""
from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

_TIMEOUT_MS = 30000

# Editierbar: die drei zu prüfenden Portale/URLs. Die StepStone-Detailseite ist der
# eigentliche HTTP2-Block-Fall; Suche + Indeed ergänzen die Sichtprüfung.
TARGET_URLS = [
    {"portal": "indeed", "kind": "search",
     "url": "https://de.indeed.com/jobs?q=softwareentwickler&l=Berlin"},
    {"portal": "stepstone", "kind": "search",
     "url": "https://www.stepstone.de/jobs/softwareentwickler/in-berlin"},
    {"portal": "stepstone", "kind": "detail",
     "url": "https://www.stepstone.de/stellenangebote--Softwareentwickler-m-w-d--000000-inline.html"},
]

# Cloudflare-Turnstile-/Challenge-Marker (Indeed) — case-insensitive.
_INDEED_BLOCK_MARKERS = ("just a moment", "cf-challenge", "cf-turnstile",
                         "checking your browser", "captcha-delivery")
# Erkennbarer Listing-/Job-Inhalt — belegt "Seite kam durch".
_CONTENT_MARKERS = ("softwareentwickler", "vollzeit", "teilzeit", "bewerben",
                    "aufgaben", "profil", "jobs")


def classify(portal: str, status: int, error: str | None, html: str) -> str:
    """Rein, netzfrei: 'PASS' (Seite kam durch) oder 'FAIL' (geblockt/leer)."""
    norm = (html or "").lower()
    if portal == "stepstone":
        # Verbindungs-Drop / HTTP2-Block wirft im goto → error gesetzt.
        if error:
            return "FAIL"
        if any(m in norm for m in _CONTENT_MARKERS):
            return "PASS"
        return "FAIL"
    if portal == "indeed":
        if status == 403 or any(m in norm for m in _INDEED_BLOCK_MARKERS):
            return "FAIL"
        if status == 200 and any(m in norm for m in _CONTENT_MARKERS):
            return "PASS"
        return "FAIL"
    return "FAIL"


def probe(url: str) -> dict:
    """Netz-I/O: rendert url über die lokale (Home-)IP. Gibt status/error/html zurück;
    jede goto-/Render-Störung landet als error-String, kein Crash."""
    try:
        with sync_playwright() as p:
            browser_obj = p.chromium.launch()
            page = browser_obj.new_page()
            resp = page.goto(url, timeout=_TIMEOUT_MS, wait_until="domcontentloaded")
            html = page.content()
            status = resp.status if resp is not None else 0
            browser_obj.close()
            return {"status": status, "error": None, "html": html}
    except Exception as e:  # noqa: BLE001 — jede goto-/Render-Störung ist ein Block-Signal
        return {"status": 0, "error": str(e), "html": ""}


def main() -> int:
    results = []
    for t in TARGET_URLS:
        r = probe(t["url"])
        verdict = classify(t["portal"], r["status"], r["error"], r["html"])
        results.append((t, verdict))
        err = f"err={r['error'][:50]}" if r["error"] else ""
        print(f"{verdict:4}  {t['portal']:9} {t['kind']:6} status={r['status']:>3}  {err}")

    portals = {t["portal"] for t, _ in results}
    green = {p for p in portals
             if all(v == "PASS" for t, v in results if t["portal"] == p)}
    ok = {"indeed", "stepstone"} <= green
    print(f"\nGrün: {sorted(green)}  →  "
          f"{'GATE PASS (exit 0)' if ok else 'GATE FAIL (exit 1)'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
