#!/bin/bash
# Foreground batch driver for PHV1 (Policy H0 Prospective Holdout V1).
# Sandbox kills background processes between tool calls, so each invocation
# runs one ~8.5-minute foreground batch under an outer timeout, then exits;
# relaunching resumes from persisted per-case rows and request artifacts.
# Usage: run_phv1_batches.sh <phase> [max_batches]
# Exit codes: 0 phase COMPLETE/SEALED; 2 provider paused (cooldown+retry) or
# smoke transport failure; 124/137 outer timeout hit (relaunch); 3 partial.
cd /home/z/my-project/guardian-of-truth || exit 4
export PYTHONUNBUFFERED=1 PYTHONPATH=src
PHASE="$1"; MAX="${2:-1}"
for i in $(seq 1 "$MAX"); do
  timeout 540 python3 scripts/evaluate_vnext_policy_phv1.py "$PHASE" --env-file .env --minutes 7.8
  code=$?
  if [ "$code" -eq 0 ]; then exit 0; fi
  if [ "$code" -eq 2 ]; then echo "PROVIDER_PAUSED: cooling down 90s"; sleep 90; fi
done
exit $code
