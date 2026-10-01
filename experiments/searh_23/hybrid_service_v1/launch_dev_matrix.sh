#!/usr/bin/env bash
set -euo pipefail
repo=${1:-/workspace/guardian/repos/hybrid-assistants-worktree}
python=/workspace/guardian/venv/bin/python
root=/workspace/guardian/results/hybrid_matrix_campaign
mkdir -p "$root"
trap 'code=$?; printf "%s\n" "$code" > "$root/dev_exit.txt"' EXIT
cd "$repo"
"$python" experiments/searh_23/hybrid_service_v1/campaign.py \
  --split dev --arms m01-phi m11-ge-gp-phi h3-native-review h3-ge-native-review \
  --max-calls 600 --max-tokens 1200000 --max-minutes 180 \
  --output-root "$root" > "$root/dev_stdout.json" 2> "$root/dev_stderr.log"
