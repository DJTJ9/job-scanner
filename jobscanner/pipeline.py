"""Pipeline-Kern: search → scrape → normalize → dedup → fresh → store.

Manueller Aufruf: python -m jobscanner.pipeline  (Scheduler 1.7 kommt später)
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

from jobscanner import config, dedup, extract, nocodb_board, scoring, storage
from jobscanner.search import FirecrawlSearchProvider, SearchProvider, discover_urls

_DEFAULT_DB = Path(__file__).parent.parent / "data" / "jobs.db"


def run(provider: SearchProvider | None = None, limit_per_query: int = 10,
        push_nocodb: bool = True, db_path: str | Path | None = None,
        today: str | None = None,
        max_scrapes_per_portal: int | None = None) -> dict:
    provider = provider or FirecrawlSearchProvider()
    today = today or _dt.date.today().isoformat()
    storage.init_db(db_path or _DEFAULT_DB)

    portals = config.load_portals()
    queries = config.load_queries()
    profile = config.load_profile()
    known = dedup.known_source_urls()

    report: dict = {"date": today, "new": 0, "known_skipped": 0, "errors": 0,
                    "portals": {p["name"]: {"urls": 0, "scraped": 0} for p in portals}}
    touched: set[str] = set()

    for portal in portals:
        stats = report["portals"][portal["name"]]
        seen_urls: set[str] = set()
        capped = False
        for role_langs in queries.values():
            if capped:
                break
            for terms in role_langs.values():
                if capped:
                    break
                for term in terms:
                    if capped:
                        break
                    for url in discover_urls(portal, term, provider, limit=limit_per_query):
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
                        raw = extract.scrape_job(url)
                        if raw is None:
                            report["errors"] += 1
                            continue
                        job = extract.to_job(raw, portal["name"], url, today)
                        if job is None:
                            report["errors"] += 1
                            continue
                        stats["scraped"] += 1
                        is_new = storage.get_job(job.fingerprint) is None
                        fp = storage.upsert_job(job)
                        known[url] = fp
                        if is_new:
                            score, reason, category = scoring.score_job(job, profile)
                            job.score, job.score_reason, job.category = score, reason, category
                            storage.update_job(fp, score=score, score_reason=reason, category=category)
                            report["new"] += 1
                            if push_nocodb:
                                row_id = nocodb_board.push_job(job)
                                storage.update_job(fp, nocodb_row_id=row_id)
    return report


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, ensure_ascii=False))
