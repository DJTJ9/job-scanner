"""Pipeline-Kern: search → scrape → normalize → dedup → fresh → store.

Manueller Aufruf: python -m jobscanner.pipeline  (Scheduler 1.7 kommt später)
"""
from __future__ import annotations

import datetime as _dt
import json
import subprocess
from pathlib import Path

from jobscanner import (archive, browser, config, dedup, extract, market, neighbors,
                        nocodb_board, scoring, search, storage)
from jobscanner.search import SearchProvider

_DEFAULT_DB = Path(__file__).parent.parent / "data" / "jobs.db"
_NOTIFY_SCRIPT = Path("/root/projekte/telegram-bot-army/scripts/telegram_notify.py")


def run(provider: SearchProvider | None = None, limit_per_query: int = 10,
        push_nocodb: bool = True, db_path: str | Path | None = None,
        today: str | None = None,
        max_scrapes_per_portal: int | None = None,
        send_report: bool = True,
        profile_name: str = "default") -> dict:
    today = today or _dt.date.today().isoformat()
    storage.init_db(db_path or _DEFAULT_DB)
    storage.migrate_yaml_profile()
    active_profiles = storage.list_profiles(active_only=True)
    profile_criteria = {p["id"]: storage.list_criteria(p["id"]) for p in active_profiles}
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

    report: dict = {"date": today, "new": 0, "known_skipped": 0, "errors": 0,
                    "profiles_scored": len(active_profiles),
                    "firecrawl_ok": browser.firecrawl_credits_ok(),
                    "portals": {p["name"]: {"urls": 0, "scraped": 0} for p in portals}}
    touched: set[str] = set()

    for portal in portals:
        stats = report["portals"][portal["name"]]
        portal_provider = provider or search.provider_for(portal)
        seen_urls: set[str] = set()
        capped = False
        for role, role_langs in queries.items():
            if capped:
                break
            for terms in role_langs.values():
                if capped:
                    break
                for term in terms:
                    if capped:
                        break
                    # Cap VOR der Suche prüfen — sonst feuert ein gecapptes Portal
                    # noch eine (bei Firecrawl teure) Such-Anfrage ab (Live-E2E 2026-07-11).
                    if (max_scrapes_per_portal is not None
                            and stats["scraped"] >= max_scrapes_per_portal):
                        capped = True
                        break
                    for url in search.discover_urls(portal, term, portal_provider,
                                                    limit=limit_per_query):
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
                            raw = extract.extract_from_text(text) if text else None
                        else:
                            raw = extract.scrape_job(
                                url,
                                fetch_method=portal.get("detail_fetch", "playwright"),
                                failover=portal.get("firecrawl_failover", False))
                        if raw is None:
                            report["errors"] += 1
                            continue
                        job = extract.to_job(raw, portal["name"], url, today)
                        if job is None:
                            report["errors"] += 1
                            continue
                        job.role = role
                        job.is_neighbor = role in neighbor_role_names
                        stats["scraped"] += 1
                        is_new = storage.get_job(job.fingerprint) is None
                        fp = storage.upsert_job(job)
                        known[url] = fp
                        if is_new:
                            for p in active_profiles:
                                score, reason, category, breakdown = scoring.criteria_score(
                                    job, p["data"], profile_criteria[p["id"]])
                                storage.upsert_job_score(
                                    p["id"], fp, score, reason, category, breakdown)
                                if p["id"] == default_profile["id"]:
                                    job.score, job.score_reason, job.category = (
                                        score, reason, category)
                                    storage.update_job(fp, score=score, score_reason=reason,
                                                       category=category)
                            if category == "Pass":
                                job.archive_path = archive.save_snapshot(job)
                                storage.update_job(fp, archive_path=job.archive_path)
                            report["new"] += 1
                            if push_nocodb:
                                row_id = nocodb_board.push_job(job)
                                storage.update_job(fp, nocodb_row_id=row_id)
    if send_report:
        jobs = storage.list_jobs()
        aggregate = market.aggregate_skills(jobs, group_by_role=True)
        stats = market.neighbor_stats(jobs)
        subprocess.run(["python", str(_NOTIFY_SCRIPT), market.format_report(aggregate, stats)],
                       check=False)
    return report


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, ensure_ascii=False))
