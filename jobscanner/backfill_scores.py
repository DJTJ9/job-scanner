"""Einmaliges Backfill: Indeed-Dup-Cleanup + Profil-Scores für Bestandsjobs.

0 Firecrawl-Credits — nur Groq-Calls. Nebeneffekt: validiert die Veto-Kalibrierung
an ~100 echten Jobs, bevor Firecrawl-Credits fließen.

Aufruf: python -m jobscanner.backfill_scores [--db PATH] [--dry-run]
--dry-run: nur Cleanup-Analyse, keine Writes, kein Scoring.
"""
from __future__ import annotations

import argparse
import time
from collections import Counter
from pathlib import Path

from jobscanner import dedup, scoring, storage

_DEFAULT_DB = Path(__file__).parent.parent / "data" / "jobs.db"
_SLEEP_S = 1.0  # Groq-Rate-Limit-Puffer zwischen Scoring-Calls


def cleanup_indeed_duplicates(dry_run: bool = False) -> dict:
    """Kanonisiert Indeed-Source-URLs (jk=) und merged Job-Zeilen mit gleichem Key."""
    by_canon: dict[str, dict[str, object]] = {}
    for job in storage.list_jobs():
        canonical = []
        seen: set[str] = set()
        changed = False
        for s in job.sources:
            url = s.get("url")
            if url and s.get("portal") == "indeed":
                canon = dedup.canonicalize_url(url, "indeed")
                if canon != url:
                    changed = True
                s = dict(s, url=canon)
                by_canon.setdefault(canon, {})[job.fingerprint] = job
            if s.get("url") in seen:
                changed = True
                continue
            seen.add(s.get("url"))
            canonical.append(s)
        job.sources = canonical
        if changed and not dry_run:
            storage.set_sources(job.fingerprint, canonical)
    removed = 0
    # Ein Job kann in mehreren jk-Gruppen auftauchen (mehrere Indeed-Quellen).
    # Wird sein Fingerprint in Gruppe A schon gelöscht, muss Gruppe B auf den
    # dortigen Keeper ausweichen statt set_sources/delete_job auf der toten
    # Fingerprint-Zeile aufzurufen (sonst gehen die dort gemergten Quellen
    # verloren — der UPDATE ist ein stiller No-Op).
    dropped_to_keeper: dict[str, object] = {}

    def resolve(j):
        while j.fingerprint in dropped_to_keeper:
            j = dropped_to_keeper[j.fingerprint]
        return j

    for fps in by_canon.values():
        if len(fps) < 2:
            continue
        keep, *drop = sorted(fps.values(),
                             key=lambda j: (j.first_seen, j.fingerprint))
        keep = resolve(keep)
        for d in drop:
            d = resolve(d)
            if d.fingerprint == keep.fingerprint:
                continue
            keep_urls = {s.get("url") for s in keep.sources}
            extra = [s for s in d.sources if s.get("url") not in keep_urls]
            if not dry_run:
                if extra:
                    keep.sources = keep.sources + extra
                    storage.set_sources(keep.fingerprint, keep.sources)
                storage.delete_job(d.fingerprint)
                dropped_to_keeper[d.fingerprint] = keep
            removed += 1
    return {"rows_removed": removed, "dry_run": dry_run}


def backfill() -> dict:
    """Scored alle Jobs ohne job_scores-Eintrag, je aktivem Profil."""
    storage.migrate_yaml_profile()
    stats: Counter = Counter()
    for p in storage.list_profiles(active_only=True):
        criteria = storage.list_criteria(p["id"])
        feedback = storage.list_feedback_with_titles(p["id"])
        todo = storage.list_jobs_without_score(p["id"])
        for i, job in enumerate(todo, 1):
            score, reason, category, breakdown = scoring.criteria_score(
                job, p["data"], criteria, feedback=feedback)
            if score is None and category is None:
                stats["errors"] += 1  # kein Upsert — Re-Run versucht es erneut
                continue
            storage.upsert_job_score(p["id"], job.fingerprint, score, reason,
                                     category, breakdown)
            if p["is_default"]:
                storage.update_job(job.fingerprint, score=score,
                                   score_reason=reason, category=category)
            stats[f"{p['name']}:{category}"] += 1
            print(f"[{p['name']}] {i}/{len(todo)}: {job.title[:50]} "
                  f"→ {category} ({score})", flush=True)
            time.sleep(_SLEEP_S)
    return dict(stats)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(_DEFAULT_DB))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    storage.init_db(args.db)
    print(cleanup_indeed_duplicates(dry_run=args.dry_run))
    if not args.dry_run:
        print(backfill())


if __name__ == "__main__":
    main()
