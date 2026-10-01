#!/usr/bin/env bash
set -euo pipefail
repo=${1:-/workspace/guardian/repos/hybrid-review-worktree}
python=/workspace/guardian/venv/bin/python
root=/workspace/guardian/results/hybrid_sealed_campaign
mkdir -p "$root"
trap 'code=$?; printf "%s\n" "$code" > "$root/main_exit.txt"' EXIT
cd "$repo"
"$python" experiments/searh_23/hybrid_service_v1/campaign.py \
  --split sealed --arms g0-direct g3-ge-gp-surface r0-refute-positive r2-ge-refute-positive h3-ge-native-review \
  --max-calls 1500 --max-tokens 2000000 --max-minutes 150 \
  --output-root "$root" > "$root/main_stdout.json" 2> "$root/main_stderr.log"
