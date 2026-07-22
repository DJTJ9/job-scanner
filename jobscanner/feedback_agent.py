"""CLI-IO für die zwei Feedback-Agenten (claude -p, siehe deploy/run_feedback_agent.sh).
Analog llm_batch.py: der Agent ruft diese Subcommands aus seinem eigenen Prompt heraus auf.
Feste Payload-Pfade statt Datei-Arg → keine Bash-Wildcard-Freigabe im allowedTools-Scope."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from jobscanner import storage

_DEFAULT_DB = Path(__file__).parent.parent / "data" / "jobs.db"
_CARDS_PATH = Path(__file__).parent.parent / "data" / "feedback_cards.json"
_INSIGHTS_PATH = Path(__file__).parent.parent / "data" / "feedback_insights.json"


def _profile_id_for(analysis_id: int) -> int:
    analysis = storage.get_analysis(analysis_id)
    if analysis is None:
        raise SystemExit(f"Analyse {analysis_id} nicht gefunden")
    return analysis["profile_id"]


def cmd_read(analysis_id: int, db_path: str | Path | None = None) -> None:
    if db_path is not None:
        storage.init_db(db_path)
    analysis = storage.get_analysis(analysis_id)
    if analysis is None:
        raise SystemExit(f"Analyse {analysis_id} nicht gefunden")
    pid = analysis["profile_id"]
    profile = storage.get_profile(pid) or {"data": {}}
    payload = {
        "analysis": {"id": analysis["id"], "profile_id": pid, "status": analysis["status"],
                     "cards": analysis["cards"], "answers": analysis["answers"]},
        "votes": storage.list_feedback_with_jobs(pid),
        "favorites": storage.list_favorites_with_titles(pid),
        "criteria": [{"key": c["key"], "label": c["label"], "weight": c["weight"]}
                     for c in storage.list_criteria(pid)],
        "preferences": profile["data"].get("preferences", []),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def cmd_write_cards(analysis_id: int, cards_path: Path | None = None,
                    db_path: str | Path | None = None) -> None:
    if db_path is not None:
        storage.init_db(db_path)
    cards = json.loads((cards_path or _CARDS_PATH).read_text(encoding="utf-8"))
    storage.save_analysis_cards(analysis_id, cards)
    storage.set_analysis_status(analysis_id, "pending_review")


def cmd_write_insights(analysis_id: int, insights_path: Path | None = None,
                       db_path: str | Path | None = None) -> None:
    if db_path is not None:
        storage.init_db(db_path)
    pid = _profile_id_for(analysis_id)
    items = json.loads((insights_path or _INSIGHTS_PATH).read_text(encoding="utf-8"))
    for it in items:
        storage.add_insight(pid, it["kind"], it.get("text", ""), payload=it.get("payload"))
    storage.set_analysis_status(analysis_id, "finalized")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(_DEFAULT_DB))
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("read", "write-cards", "write-insights"):
        p = sub.add_parser(name)
        p.add_argument("analysis_id", type=int)
    args = parser.parse_args()
    storage.init_db(args.db)
    if args.command == "read":
        cmd_read(args.analysis_id)
    elif args.command == "write-cards":
        cmd_write_cards(args.analysis_id)
    elif args.command == "write-insights":
        cmd_write_insights(args.analysis_id)


if __name__ == "__main__":
    main()
