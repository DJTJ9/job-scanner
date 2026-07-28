"""Sofort-Pass: läuft als systemd-Service direkt nach dem Scoring-Agent. Mailt je aktivem
Profil mit immediate=true die neuen starken Treffer (Pass, score >= Schwelle, notified_at
IS NULL) und markiert sie. Teilt den notified_at-Marker mit dem Digest → kein Doppel-Spam.
Synct außerdem die Inbox (kanalunabhängig, wie der Digest-Pass)."""
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
    for profile in storage.list_profiles(active_only=True):
        pid, uid = profile["id"], profile["user_id"]
        if uid is None:
            continue
        pref = storage.get_notify_pref(profile["data"])
        if pref["inbox"]:
            storage.sync_inbox_notifications(pid)
        if not pref.get("immediate"):
            continue
        rows = storage.list_immediate_matches(pid, IMMEDIATE_SCORE_THRESHOLD)
        if not rows:
            continue
        stats["members"] += 1
        stats["matches"] += len(rows)
        user = storage.get_user(uid)
        if user and user.get("email"):
            sent = False
            for r in rows:
                try:
                    mailer.send_immediate_match(user["email"], pid, r, _BASE_URL)
                    sent = True
                except Exception as exc:  # SMTP-Fehler pro Match isolieren
                    print(f"notify_immediate: send failed for profile {pid}: {exc}")
            if sent:
                stats["emails"] += 1
        storage.mark_notified(pid, [r["fingerprint"] for r in rows])
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(_DEFAULT_DB))
    args = parser.parse_args()
    print(json.dumps(run_immediate_notifications(args.db), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
