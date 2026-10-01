#!/usr/bin/env bash
set -euo pipefail
repo=${1:-/workspace/guardian/repos/hybrid-assistants-worktree}
python=/workspace/guardian/venv/bin/python
root=/workspace/guardian/results/hybrid_review_campaign
mkdir -p "$root"
trap 'code=$?; printf "%s\n" "$code" > "$root/dev_exit.txt"' EXIT
cd "$repo"
"$python" experiments/searh_23/hybrid_service_v1/campaign.py \
  --split dev --arms r0-refute-positive r1-review-all r2-ge-refute-positive r3-ge-review-all \
  --max-calls 800 --max-tokens 1000000 --max-minutes 180 \
  --output-root "$root" > "$root/dev_stdout.json" 2> "$root/dev_stderr.log"
