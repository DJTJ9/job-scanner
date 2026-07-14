"""Pipeline-Kern: search → scrape → normalize → dedup → fresh → store (raw, kein LLM).

Scoring passiert jetzt im nachgelagerten Agent-Batch-Lauf (llm_batch.py) — dieses Modul
liefert nur noch rohe, unextrahierte Jobs. Report-Versand läuft getrennt über
send_report(), weil Scores erst nach dem Agent-Lauf existieren.

Manueller Aufruf: python -m jobscanner.pipeline
Report senden (nach dem Agent-Lauf): python -m jobscanner.pipeline --send-report
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import subprocess
from pathlib import Path

from jobscanner import browser, config, dedup, extract, market, neighbors, search, storage
from jobscanner.search import SearchProvider

_DEFAULT_DB = Path(__file__).parent.parent / "data" / "jobs.db"
_REPORT_PATH = Path(__file__).parent.parent / "data" / "last_discover_report.json"
_NOTIFY_SCRIPT = Path("/root/projekte/telegram-bot-army/scripts/telegram_notify.py")


def run(provider: SearchProvider | None = None, limit_per_query: int = 10,
        db_path: str | Path | None = None, today: str | None = None,
        max_scrapes_per_portal: int | None = None,
        profile_name: str = "default") -> dict:
    today = today or _dt.date.today().isoformat()
    storage.init_db(db_path or _DEFAULT_DB)
    browser.reset_credits()
    fc_before = browser.credits_remaining()
    storage.migrate_yaml_profile()
    active_profiles = storage.list_profiles(active_only=True)
    default_profile = next(
        (p for p in active_profiles if p["is_default"]), active_profiles[0])

    portals = config.load_portals()
    core_queries = config.load_queries()
    profile = default_profile["data"]  # Neighbors laufen weiter nur fürs Default-Profil
    neighbor_roles = neighbors.get_neighbor_roles(
        profile, profile_name, set(core_queries), today=today)
    queries = {**core_queries, **{name: r["terms"] for name, r in neighbor_roles.items()}}
    neighbor_role_names = set(neighbor_roles)
    known = dedup.known_source_urls()
    touched: set[str] = set()

    report: dict = {"date": today, "new": 0, "known_skipped": 0, "errors": 0,
                    "firecrawl_ok": browser.firecrawl_credits_ok(),
                    "portals": {p["name"]: {"urls": 0, "scraped": 0} for p in portals}}

    for portal in portals:
        stats = report["portals"][portal["name"]]
        portal_provider = provider or search.provider_for(portal)
        seen_urls: set[str] = set()
        capped = False
        max_terms = portal.get("max_search_terms")
        terms_searched = 0
        for role, role_langs in queries.items():
            if capped:
                break
            if portal.get("skip_neighbor_roles") and role in neighbor_role_names:
                continue
            for terms in role_langs.values():
                if capped:
                    break
                for term in terms:
                    if capped:
                        break
                    if max_terms is not None and terms_searched >= max_terms:
                        capped = True
                        break
                    if (max_scrapes_per_portal is not None
                            and stats["scraped"] >= max_scrapes_per_portal):
                        capped = True
                        break
                    terms_searched += 1
                    for url in search.discover_urls(portal, term, portal_provider,
                                                    limit=limit_per_query):
                        url = dedup.canonicalize_url(url, portal["name"])
                        if (max_scrapes_per_portal is not None
                                and stats["scraped"] >= max_scrapes_per_portal):
                            capped = True
                            break
                        if url in seen_urls:
                            continue
                        seen_urls.add(url)
                        stats["urls"] += 1
                        if url in known:
                            fp = known[url]
                            if fp not in touched:
                                dedup.touch_known(fp, today)
                                touched.add(fp)
                            report["known_skipped"] += 1
                            continue
                        if portal.get("detail_fetch") == "api":
                            text = getattr(portal_provider, "descriptions", {}).get(url)
                            raw_text = extract.clean_api_text(text) if text else None
                        else:
                            raw_text = extract.fetch_raw_text(
                                url,
                                fetch_method=portal.get("detail_fetch", "playwright"),
                                failover=portal.get("firecrawl_failover", False))
                        if not raw_text:
                            report["errors"] += 1
                            continue
                        stats["scraped"] += 1
                        fp = storage.insert_raw_job(
                            url, portal["name"], raw_text, today,
                            role=role, is_neighbor=role in neighbor_role_names)
                        known[url] = fp
                        report["new"] += 1
    fc_after = browser.credits_remaining()
    real = (fc_before - fc_after
            if fc_before is not None and fc_after is not None else None)
    report["credits"] = {"estimated": browser.credits_spent(), "real": real,
                         "budget": config.firecrawl_budget()}
    _REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                            encoding="utf-8")
    return report


def send_report(db_path: str | Path | None = None, today: str | None = None) -> dict:
    """Versendet den Markt-Report — getrennt vom Discover-Lauf, weil Scores erst im
    nachgelagerten Agent-Batch-Lauf entstehen. Vom Agent nach dem letzten write-batch
    aufgerufen (python -m jobscanner.pipeline --send-report)."""
    storage.init_db(db_path or _DEFAULT_DB)
    if not _REPORT_PATH.exists():
        return {"sent": False, "reason": "kein Discover-Report vorhanden"}
    discover_report = json.loads(_REPORT_PATH.read_text(encoding="utf-8"))
    today = today or discover_report.get("date") or _dt.date.today().isoformat()
    all_jobs = storage.list_jobs()
    new_jobs = [j for j in storage.list_jobs(first_seen=today) if j.category is not None]
    aggregate = market.aggregate_skills(all_jobs, group_by_role=True)
    stats = market.neighbor_stats(all_jobs)
    subprocess.run(["python", str(_NOTIFY_SCRIPT),
                    market.format_report(aggregate, stats, new_jobs=new_jobs,
                                         credits=discover_report.get("credits"))],
                   check=False)
    return {"sent": True, "new_scored": len(new_jobs)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(_DEFAULT_DB))
    parser.add_argument("--send-report", action="store_true",
                        help="Nur den Report des letzten Discover-Laufs versenden")
    parser.add_argument("--today", default=None)
    args = parser.parse_args()
    if args.send_report:
        print(json.dumps(send_report(args.db, today=args.today),
                         indent=2, ensure_ascii=False))
    else:
        print(json.dumps(run(db_path=args.db, today=args.today),
                         indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
