# Job Portal Scanner

Durchsucht Jobportale nach passenden Stellen, normalisiert sie in ein lokales
SQLite-Datenmodell und spiegelt neue Jobs in das NocoDB-Board "Job Scanner Jobs".

## Struktur

- `jobscanner/models.py` — `Job`-Dataclass + Fingerprint-Normalisierung
- `jobscanner/storage.py` — SQLite-Schicht (`data/jobs.db`, Quelle der Wahrheit)
- `jobscanner/nocodb_board.py` — NocoDB-Anzeige-Board (Credentials aus `telegram-bot-army/.env`)

## Tests

    python3 -m pytest tests/ -v

## Pipeline-Lauf (Job-Ingestion)

    python3 -m jobscanner.pipeline

Durchsucht StepStone, Arbeitsagentur, Stellenanzeigen.de und Indeed mit den
Kern-Queries aus `jobscanner/queries.yaml`, extrahiert Listings via Firecrawl
(Schema in `jobscanner/extract.py`), dedupliziert per Fingerprint und speichert
nach `data/jobs.db` (SQLite, Quelle der Wahrheit) + NocoDB-Board "Job Scanner Jobs".

- Profil: `jobscanner/profile.yaml` · Portale: `jobscanner/portals.yaml`
- Voraussetzung: `firecrawl --status` → Authenticated
- Zweiter Lauf am selben Tag meldet `new: 0` (Frische-Filter)
- Kosten-Deckel für Test-Läufe: `pipeline.run(limit_per_query=2, max_scrapes_per_portal=3)`
- Scheduler (täglich) kommt in einer späteren Runde
