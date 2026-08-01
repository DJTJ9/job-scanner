"""Sofort-Pass: läuft als systemd-Service direkt nach dem Scoring-Agent. Mailt je Member mit
immediate=true genau eine Mail pro Pass — die neuen starken Treffer (Pass, score >= Schwelle,
notified_at IS NULL) aller seiner aktiven Profile, nach Profil gegliedert — und markiert sie.
Teilt den notified_at-Marker mit dem Digest → kein Doppel-Spam. Synct außerdem die Inbox
(kanalunabhängig, wie der Digest-Pass)."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from jobscanner import storage
from jobscanner.web import mailer

_DEFAULT_DB = Path(__file__).parent.parent / "data" / "jobs.db"
_BASE_URL = os.environ.get("JOBSCANNER_BASE_URL", "https://job-scanner.thinkshark.de")
IMMEDIATE_SCORE_THRESHOLD = int(os.environ.get("IMMEDIATE_SCORE_THRESHOLD", "90"))


def run_immediate_notifications(db_path: str | Path | None = None) -> dict:
    if db_path is not None:
        storage.init_db(db_path)
    stats = {"members": 0, "emails": 0, "matches": 0}
    by_user: dict[int, dict] = {}
    for profile in storage.list_profiles(active_only=True):
        pid, uid = profile["id"], profile["user_id"]
        if uid is None:
            continue
        # Inbox entkoppelt: läuft für jedes aktive Profil, unabhängig von der Mail-Präferenz.
        storage.sync_inbox_notifications(pid)
        user = storage.get_user(uid)
        if not (user and user.get("role") == "owner"):
            continue  # Member bekommen nur die Inbox, nie eine Mail.
        pref = storage.get_notify_pref(profile["data"])
        if not pref.get("immediate"):
            continue
        rows = storage.list_immediate_matches(pid, IMMEDIATE_SCORE_THRESHOLD)
        if not rows:
            continue
        # Eine Mail pro User: Treffer aller Profile sammeln, erst nach dem Loop senden.
        entry = by_user.setdefault(uid, {"email": user.get("email"), "groups": []})
        entry["groups"].append({"profile": profile["name"], "pid": pid, "rows": rows})
        stats["matches"] += len(rows)
    for uid, entry in by_user.items():
        stats["members"] += 1
        if entry["email"]:
            try:
                mailer.send_immediate_match(entry["email"], entry["groups"], _BASE_URL)
                stats["emails"] += 1
            except Exception as exc:  # SMTP-Fehler isolieren, Marker trotzdem setzen
                print(f"notify_immediate: send failed for user {uid}: {exc}")
        for g in entry["groups"]:
            storage.mark_notified(g["pid"], [r["fingerprint"] for r in g["rows"]])
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(_DEFAULT_DB))
    args = parser.parse_args()
    print(json.dumps(run_immediate_notifications(args.db), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
