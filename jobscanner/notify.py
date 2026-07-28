"""Notify-Pass: läuft als systemd-Timer nach dem Scoring. Meldet je aktivem Profil die
neuen Top-Treffer (category='Pass', notified_at IS NULL) per Digest-Email und markiert sie.
Löst KEINE Scans/Scorings aus — meldet nur bestehende Ergebnisse."""
from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path

from jobscanner import storage
from jobscanner.web import mailer

_DEFAULT_DB = Path(__file__).parent.parent / "data" / "jobs.db"
_BASE_URL = os.environ.get("JOBSCANNER_BASE_URL", "https://job-scanner.thinkshark.de")


def run_notifications(db_path: str | Path | None = None, today: date | None = None) -> dict:
    if db_path is not None:
        storage.init_db(db_path)
    if today is None:
        today = date.today()
    stats = {"members": 0, "emails": 0, "matches": 0}
    for profile in storage.list_profiles(active_only=True):
        pid, uid = profile["id"], profile["user_id"]
        if uid is None:
            continue
        pref = storage.get_notify_pref(profile["data"])
        if pref["inbox"]:
            storage.sync_inbox_notifications(pid)
        email_mode = pref["email_mode"]
        due = email_mode == "daily" or (email_mode == "weekly" and today.weekday() == 0)
        if not due:
            continue
        rows = storage.list_unnotified_top_matches(pid)
        if not rows:
            continue
        stats["members"] += 1
        stats["matches"] += len(rows)
        user = storage.get_user(uid)
        if user and user.get("email"):
            try:
                mailer.send_match_digest(user["email"], pid, rows, _BASE_URL)
                stats["emails"] += 1
            except Exception as exc:  # SMTP-Fehler pro Member isolieren
                print(f"notify: send failed for profile {pid}: {exc}")
                continue
        storage.mark_notified(pid, [r["fingerprint"] for r in rows])
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(_DEFAULT_DB))
    args = parser.parse_args()
    print(json.dumps(run_notifications(args.db), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
