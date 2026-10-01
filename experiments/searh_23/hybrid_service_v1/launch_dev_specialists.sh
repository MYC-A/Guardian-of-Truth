#!/usr/bin/env bash
# Run three pinned native checkers in separate processes, one GPU model at a time.
set -euo pipefail
repo=/workspace/guardian/repos/hybrid-assistants-worktree
python=/workspace/guardian/venv/bin/python
root=/workspace/guardian/results/hybrid_specialists
mkdir -p "$root"
trap 'code=$?; printf "%s\n" "$code" > "$root/dev_exit.txt"' EXIT
if [[ -n "$(git -C "$repo" status --porcelain)" ]]; then
  echo "refusing dirty checkout" >&2
  exit 2
fi
git -C "$repo" rev-parse HEAD > "$root/dev_launch_commit.txt"
date -u +'%Y-%m-%dT%H:%M:%SZ' > "$root/dev_started_at.txt"
for model in factcg minicheck granite; do
  echo "Starting $model" >&2
  "$python" "$repo/experiments/searh_23/hybrid_service_v1/specialist_run.py" \
    --model "$model" --split dev --max-minutes 90 \
    > "$root/dev_${model}_stdout.json" 2> "$root/dev_${model}_stderr.log"
  "$python" - "$root/dev_${model}_stdout.json" <<'PY'
import json, sys
result = json.load(open(sys.argv[1], encoding="utf-8"))
if result["status"]["state"] != "SUCCEEDED" or result["summary"] is None:
    raise SystemExit("native run did not complete")
print(result["directory"])
PY
done
date -u +'%Y-%m-%dT%H:%M:%SZ' > "$root/dev_finished_at.txt"
