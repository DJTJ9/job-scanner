#!/bin/bash
set -euo pipefail
cd /opt/jobscanner
PASS="$1"       # analyze | synthesize
AID="$2"        # analysis_id
case "$PASS" in
  analyze)   PROMPT_FILE="deploy/feedback_analysis_prompt.txt" ;;
  synthesize) PROMPT_FILE="deploy/feedback_synthesis_prompt.txt" ;;
  *) echo "unknown pass: $PASS" >&2; exit 2 ;;
esac
PROMPT="$(cat "$PROMPT_FILE")"$'\n\n'"Analysis-ID für diesen Lauf: $AID"
claude -p "$PROMPT" \
  --permission-mode acceptEdits \
  --allowedTools "Bash(python3 -m jobscanner.feedback_agent read $AID)" \
               "Bash(python3 -m jobscanner.feedback_agent write-cards $AID)" \
               "Bash(python3 -m jobscanner.feedback_agent write-insights $AID)" \
               "Write(/opt/jobscanner/data/feedback_cards.json)" \
               "Write(/opt/jobscanner/data/feedback_insights.json)" \
  --output-format text
