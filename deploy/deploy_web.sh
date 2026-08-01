#!/bin/bash
# Deploy des Web-Dienstes: friert /opt/jobscanner-live auf einen committeten Stand ein
# und startet den Dienst neu. Code, Templates und Static stammen danach aus EINEM Commit.
# Ohne Argument: aktueller master-HEAD des Arbeits-Checkouts.
set -euo pipefail

WORK=/opt/jobscanner
LIVE=/opt/jobscanner-live
HASH="${1:-$(git -C "$WORK" rev-parse master)}"

git -C "$LIVE" checkout --detach "$HASH"
systemctl restart jobscanner-web.service
sleep 2
systemctl is-active jobscanner-web.service
curl -sf localhost:8010/ -o /dev/null
echo "deployed: $(git -C "$LIVE" rev-parse --short HEAD)"
