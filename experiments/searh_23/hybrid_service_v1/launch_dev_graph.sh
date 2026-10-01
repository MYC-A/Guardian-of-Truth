#!/usr/bin/env bash
# Run inside a detached tmux session on vast_me. The Python runner owns its
# per-run status/checkpoints; this wrapper preserves process exit separately.
set -u
ROOT=/workspace/guardian/repos/hybrid-assistants-worktree
JOBS=/workspace/guardian/results/hybrid_campaigns
mkdir -p "$JOBS"
cd "$ROOT" || exit 99
/workspace/guardian/venv/bin/python \
  experiments/searh_23/hybrid_service_v1/campaign.py \
  --split dev \
  --arms g0-direct g1-ge g2-gp-surface g3-ge-gp-surface gplain-evidence \
  --max-calls 1000 --max-tokens 1200000 --max-minutes 180 \
  >> "$JOBS/dev_graph_stdout.log" 2>&1
code=$?
printf '%s\n' "$code" > "$JOBS/dev_graph_exit.txt"
exit "$code"
