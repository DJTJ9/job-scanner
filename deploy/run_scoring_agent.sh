#!/bin/bash
set -euo pipefail
cd /opt/jobscanner
claude -p "$(cat deploy/scoring_agent_prompt.txt)" \
  --permission-mode acceptEdits \
  --allowedTools "Bash(python3 -m jobscanner.llm_batch list-pending)" \
               "Bash(python3 -m jobscanner.llm_batch write-batch)" \
               "Bash(python3 -m jobscanner.pipeline --send-report)" \
               "Write(/opt/jobscanner/data/pending_batch.json)" \
  --output-format text
