"""CLI für den geplanten Claude-Agent-Batch-Lauf: liest pending Jobs, schreibt
Extraktion + Scoring zurück. Ersetzt Groq im Ingestion-Pfad — der 'LLM-Call' ist jetzt
der Agent selbst (claude -p headless), der dieses CLI aus seinem eigenen Prompt heraus
aufruft (siehe deploy/scoring_agent_prompt.txt)."""
from __future__ import annotations

import argparse
import datetime as _dt
import json
from pathlib import Path

from jobscanner import archive, extract, nocodb_board, scoring, storage

_DEFAULT_DB = Path(__file__).parent.parent / "data" / "jobs.db"
_DEFAULT_LIMIT = 30
# Fester Pfad statt Datei-Arg auf der CLI — vermeidet eine `Bash(... *)`-Wildcard-Freigabe
# im Agent-allowedTools-Scope (raw_text aus gescrapten Anzeigen ist Fremdinhalt, siehe
# Prompt-Injection-Hinweis in deploy/scoring_agent_prompt.txt).
_BATCH_PATH = Path(__file__).parent.parent / "data" / "pending_batch.json"


def list_pending(db_path: str | Path | None = None, limit: int = _DEFAULT_LIMIT) -> dict:
    storage.init_db(db_path or _DEFAULT_DB)
    storage.migrate_yaml_profile()
    jobs = storage.list_pending_extraction(limit=limit)
    profiles = []
    for p in storage.list_profiles(active_only=True):
        profiles.append({
            "id": p["id"],
            "data": p["data"],
            "criteria": [{"key": c["key"], "label": c["label"], "weight": c["weight"]}
                        for c in storage.list_criteria(p["id"]) if c["weight"] > 0],
            "no_gos": p["data"].get("no_gos", []),
            "preferences": p["data"].get("preferences", []),
            "feedback": storage.list_feedback_with_titles(p["id"]),
        })
    active_profiles = storage.list_profiles(active_only=True)
    default_id = next((p["id"] for p in active_profiles if p["is_default"]), None)
    kept = []
    for j in storage.list_unscored_extracted(limit=limit):
        job = storage.get_job(j["fingerprint"])
        label = scoring.rule_filter(job) if job is not None else None
        if not label:
            kept.append(j)
            continue
        # rule_filter-Veto: direkt als No-Go schreiben statt teuer scoren lassen —
        # repliziert das write_batch-No-Go-Schreibverhalten (llm_batch:75-93).
        for p in active_profiles:
            storage.upsert_job_score(p["id"], j["fingerprint"], 0,
                                     f"No-Go: {label}", "No-Go", {})
            if p["id"] == default_id:
                storage.update_job(j["fingerprint"], score=0,
                                   score_reason=f"No-Go: {label}", category="No-Go")
        storage.log_event("scoring_saved",
                          meta={"label": label, "profiles": len(active_profiles),
                                "fingerprint": j["fingerprint"]})
    return {"jobs": jobs, "to_score": kept, "profiles": profiles}


def write_batch(entries: list[dict], db_path: str | Path | None = None,
                today: str | None = None, push_nocodb: bool = True) -> dict:
    storage.init_db(db_path or _DEFAULT_DB)
    today = today or _dt.date.today().isoformat()
    active_profiles = storage.list_profiles(active_only=True)
    default_profile = next(p for p in active_profiles if p["is_default"])
    criteria_by_profile = {p["id"]: storage.list_criteria(p["id"]) for p in active_profiles}

    stats = {"extracted": 0, "skipped_extraction": 0, "scored": 0, "skipped_scoring": 0}
    for entry in entries:
        if "extraction" in entry:
            raw_fp = entry["fingerprint"]
            # portal/url sind Platzhalter: storage.apply_extraction() liest die echten
            # Quellen aus der Raw-Zeile und überschreibt job.sources ohnehin.
            job = extract.to_job(entry["extraction"], portal="", url="", today=today)
            if job is None:
                stats["skipped_extraction"] += 1
                continue
            fp = storage.apply_extraction(raw_fp, job)
            stats["extracted"] += 1
        else:
            # score-only: Job ist bereits extrahiert (Catch-up der Re-Pick-Lücke), nur bewerten.
            fp = entry["fingerprint"]
            job = storage.get_job(fp)
            if job is None:
                stats["skipped_scoring"] += 1
                continue

        for profile in active_profiles:
            pid = profile["id"]
            result = entry.get("scores", {}).get(str(pid))
            if result is None:
                stats["skipped_scoring"] += 1
                continue
            no_go = scoring.rule_filter(job)
            if no_go:
                score, reason, category, breakdown = 0, f"No-Go: {no_go}", "No-Go", {}
            elif result.get("veto"):
                score, reason, category, breakdown = (
                    0, f"No-Go: {result['veto']}", "No-Go", {})
            else:
                breakdown = result.get("kriterien", {})
                score = scoring.compute_weighted_score(breakdown, criteria_by_profile[pid])
                if score is None:
                    stats["skipped_scoring"] += 1
                    continue
                category = scoring.category_for_score(score)
                reason = scoring.top_reasons(breakdown, criteria_by_profile[pid])
            storage.upsert_job_score(pid, fp, score, reason, category, breakdown)
            stats["scored"] += 1
            if pid == default_profile["id"]:
                job.score, job.score_reason, job.category = score, reason, category
                storage.update_job(fp, score=score, score_reason=reason, category=category)
                if category == "Pass":
                    job.archive_path = archive.save_snapshot(job)
                    storage.update_job(fp, archive_path=job.archive_path)

        if push_nocodb:
            row_id = nocodb_board.push_job(job)
            storage.update_job(fp, nocodb_row_id=row_id)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(_DEFAULT_DB))
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list-pending")
    p_list.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)

    p_write = sub.add_parser("write-batch")
    p_write.add_argument("--today", default=None)
    p_write.add_argument("--no-nocodb", action="store_true")

    args = parser.parse_args()
    if args.command == "list-pending":
        print(json.dumps(list_pending(args.db, limit=args.limit),
                         ensure_ascii=False, indent=2))
    elif args.command == "write-batch":
        entries = json.loads(_BATCH_PATH.read_text(encoding="utf-8"))
        result = write_batch(entries, args.db, today=args.today,
                             push_nocodb=not args.no_nocodb)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
