"""Einmal-Migration: bestehende Owner-Profile 9 → 25 Kriterien.

Aufruf auf dem Server:  python -m jobscanner.scripts.migrate_owner_criteria
"""
from jobscanner import storage


def main() -> None:
    storage.init_db("data/jobs.db")
    n = storage.migrate_owner_criteria_to_weights()
    print(f"Migriert: {n} Profil(e)")


if __name__ == "__main__":
    main()
