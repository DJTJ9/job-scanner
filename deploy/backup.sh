#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/root/projekte/job-scanner"
DB="$PROJECT_DIR/data/jobs.db"
BACKUP_DIR="$PROJECT_DIR/data/backups"
NOTIFY="/root/projekte/telegram-bot-army/scripts/telegram_notify.py"
KEEP=14

notify_fail() {
    python "$NOTIFY" "❌ Job-Scanner Backup failed: $1" || true
    echo "BACKUP FAILED: $1" >&2
    exit 1
}

mkdir -p "$BACKUP_DIR"
stamp="$(date +%Y%m%d-%H%M%S)"
tmp="$(mktemp /tmp/jobs-XXXXXX.db)"
trap 'rm -f "$tmp"' EXIT

sqlite3 "$DB" ".backup '$tmp'" || notify_fail "sqlite .backup exit $?"
[ -s "$tmp" ] || notify_fail "snapshot ist 0 Byte"

out="$BACKUP_DIR/jobs-$stamp.db.gz"
gzip -c "$tmp" > "$out" || notify_fail "gzip exit $?"
[ -s "$out" ] || notify_fail "gz-Datei ist 0 Byte"

# Rotation: älteste über KEEP hinaus löschen (nach Name = chronologisch sortierbar)
ls -1 "$BACKUP_DIR"/jobs-*.db.gz 2>/dev/null | sort | head -n -"$KEEP" | while read -r old; do
    rm -f "$old"
done

echo "OK: $out"
