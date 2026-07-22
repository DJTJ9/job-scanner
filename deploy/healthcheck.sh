#!/usr/bin/env bash
set -euo pipefail

NOTIFY="/root/projekte/telegram-bot-army/scripts/telegram_notify.py"
URL="http://127.0.0.1:8010/"

if curl -sf --max-time 10 -o /dev/null "$URL"; then
    echo "OK: web-ui up"
    exit 0
fi

python "$NOTIFY" "❌ Job-Scanner Web-UI down (kein HTTP 200 von $URL)" || true
echo "WEB-UI DOWN" >&2
exit 1
