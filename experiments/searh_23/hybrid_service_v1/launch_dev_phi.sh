#!/usr/bin/env bash
# Bounded API-backed formal shadow pass; does not use GPU or inspect gold.
set -euo pipefail
repo=/workspace/guardian/repos/hybrid-assistants-worktree
python=/workspace/guardian/venv/bin/python
root=/workspace/guardian/results/hybrid_phi_shadow
mkdir -p "$root"
trap 'code=$?; printf "%s\n" "$code" > "$root/dev_exit.txt"' EXIT
if [[ -n "$(git -C "$repo" status --porcelain)" ]]; then
  echo "refusing dirty checkout" >&2
  exit 2
fi
git -C "$repo" rev-parse HEAD > "$root/dev_launch_commit.txt"
"$python" "$repo/experiments/searh_23/hybrid_service_v1/phi_shadow_run.py" \
  --split dev --max-calls 90 --max-tokens 400000 --max-minutes 120 \
  > "$root/dev_stdout.json" 2> "$root/dev_stderr.log"
"$python" - "$root/dev_stdout.json" <<'PY'
import json, sys
result = json.load(open(sys.argv[1], encoding="utf-8"))
if result["status"]["state"] != "SUCCEEDED":
    raise SystemExit("formal shadow run did not complete")
print(result["directory"])
PY
date -u +'%Y-%m-%dT%H:%M:%SZ' > "$root/dev_finished_at.txt"
