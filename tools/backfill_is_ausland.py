#!/usr/bin/env python3
"""Einmal-Backfill: setzt jobs.is_ausland nach der aktuellen Zielraum-Regel (DE/AT/NL)
neu. Nötig nach der Regeländerung vom 2026-08-02 — die geschlossene US-ZIP-Lücke kippt
US-Jobs auf 1, AT/NL-Jobs kippen auf 0. Es wird nichts gelöscht, nur umklassifiziert.

    python -m tools.backfill_is_ausland --dry-run
    python -m tools.backfill_is_ausland
"""
import argparse
import sqlite3
from pathlib import Path

from jobscanner.search import classify_location

DEFAULT_DB = Path(__file__).parent.parent / "data" / "jobs.db"


def backfill(db_path: str | Path, dry_run: bool = False) -> list[tuple[str, str, int, int]]:
    """Gibt die abweichenden Zeilen als (fingerprint, location, alt, neu) zurück und
    schreibt sie (außer bei dry_run)."""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT fingerprint, location, is_ausland FROM jobs").fetchall()
        geaendert = []
        for fp, loc, alt in rows:
            neu = int(classify_location(loc or ""))
            if neu != int(alt or 0):
                geaendert.append((fp, loc or "", int(alt or 0), neu))
        if geaendert and not dry_run:
            conn.executemany("UPDATE jobs SET is_ausland = ? WHERE fingerprint = ?",
                             [(neu, fp) for fp, _loc, _alt, neu in geaendert])
            conn.commit()
        return geaendert
    finally:
        conn.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    geaendert = backfill(args.db, dry_run=args.dry_run)
    for fp, loc, alt, neu in geaendert:
        print(f"{alt} -> {neu}  {loc!r}  ({fp})")
    prefix = "[dry-run] " if args.dry_run else ""
    print(f"{prefix}{len(geaendert)} von insgesamt geprüften Zeilen geändert.")


if __name__ == "__main__":
    main()
