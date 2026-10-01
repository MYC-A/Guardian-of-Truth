#!/usr/bin/env bash
set -euo pipefail
repo=${1:-/workspace/guardian/repos/hybrid-frontend-worktree}
python=/workspace/guardian/venv/bin/python
root=/workspace/guardian/results/hybrid_translation_models
mkdir -p "$root"
cd "$repo"
trap 'code=$?; printf "%s\n" "$code" > "$root/exit.txt"' EXIT
for model in mistral/codestral-2508 ollama/kimi-k2.7-code mistral/mistral-small-2603; do
  name=${model//\//_}
  "$python" experiments/searh_23/hybrid_service_v1/phi_shadow_run.py \
    --split dev --case-ids-file experiments/searh_23/hybrid_service_v1/dataset/translation_models_v1/case_ids.json \
    --model "$model" --max-calls 16 --max-tokens 120000 --max-minutes 45 \
    --output-root "$root" > "$root/${name}_stdout.json" 2> "$root/${name}_stderr.log"
done
