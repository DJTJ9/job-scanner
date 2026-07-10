# Job Portal Scanner

Durchsucht Jobportale nach passenden Stellen, normalisiert sie in ein lokales
SQLite-Datenmodell und spiegelt neue Jobs in das NocoDB-Board "Job Scanner Jobs".

## Struktur

- `jobscanner/models.py` — `Job`-Dataclass + Fingerprint-Normalisierung
- `jobscanner/storage.py` — SQLite-Schicht (`data/jobs.db`, Quelle der Wahrheit)
- `jobscanner/nocodb_board.py` — NocoDB-Anzeige-Board (Credentials aus `telegram-bot-army/.env`)

## Tests

    python3 -m pytest tests/ -v
