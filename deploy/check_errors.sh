#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/root/projekte/job-scanner"
REPORT="$PROJECT_DIR/data/last_discover_report.json"
NOTIFY="/root/projekte/telegram-bot-army/scripts/telegram_notify.py"

[ -f "$REPORT" ] || { echo "kein Report — skip"; exit 0; }

errors="$(python -c "import json,sys; print(json.load(open(sys.argv[1])).get('errors',0))" "$REPORT")"

if [ "$errors" -gt 0 ]; then
    python "$NOTIFY" "⚠️ Job-Scanner Discover: $errors Fehler im letzten Lauf (last_discover_report.json)" || true
    echo "ALERT: errors=$errors"
else
    echo "OK: errors=0"
fi
exit 0
