#!/bin/bash
set -euo pipefail
cd /root/projekte/job-scanner
claude -p "$(cat deploy/scoring_agent_prompt.txt)" \
  --permission-mode acceptEdits \
  --allowedTools "Bash(python3 -m jobscanner.llm_batch *)" \
               "Bash(python3 -m jobscanner.pipeline --send-report)" \
               "Write(/root/projekte/job-scanner/data/*.json)" \
  --output-format text
