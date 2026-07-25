#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/opt/jobscanner"
DB="$PROJECT_DIR/data/jobs.db"

BACKUP="${1:-}"
[ -n "$BACKUP" ] || { echo "Usage: restore.sh <backup.db.gz>" >&2; exit 2; }
[ -f "$BACKUP" ] || { echo "Backup nicht gefunden: $BACKUP" >&2; exit 2; }

echo "ACHTUNG: '$DB' wird durch '$BACKUP' ersetzt. jobscanner-web wird gestoppt."
read -r -p "Fortfahren? (yes/NO) " ans
[ "$ans" = "yes" ] || { echo "Abgebrochen."; exit 1; }

pre="$DB.pre-restore-$(date +%Y%m%d-%H%M%S)"
systemctl stop jobscanner-web
cp -a "$DB" "$pre" 2>/dev/null || true   # Sicherung des aktuellen Stands
gunzip -c "$BACKUP" > "$DB"
# WAL/SHM des alten Stands verwerfen (Snapshot ist bereits konsistent)
rm -f "$DB-wal" "$DB-shm"
systemctl start jobscanner-web

echo "Restore OK. Vorheriger Stand gesichert: $pre"
