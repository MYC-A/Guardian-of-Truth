#!/bin/bash
# Finite offline evaluation, supervised externally; no inference HTTP service.
set -euo pipefail
root=/workspace/guardian-lab-20261018
job=${1:?job name required}
dataset=${2:?dataset required}
config=${3:?config required}
seconds=${4:-7200}
[[ "$job" =~ ^[a-zA-Z0-9_-]+$ && "$dataset" =~ ^[a-zA-Z0-9_-]+$ && "$seconds" =~ ^[0-9]+$ ]]
test -f "$root/RUNTIME_READY.json"
test -f "$root/models/qwen36-awq/VERIFIED.json"
test ! -e "$root/runs/$job"
export PYTHONPATH="$root/code/src"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 VLLM_NO_USAGE_STATS=1
export TOKENIZERS_PARALLELISM=false
cd "$root/code"
nvidia-smi --query-gpu=timestamp,memory.used,utilization.gpu,power.draw --format=csv -l 1 > "$root/logs/$job-vram.csv" &
sampler=$!
trap 'kill "$sampler" 2>/dev/null || true' EXIT
set +e
timeout --signal=TERM --kill-after=30 "$((seconds+300))" "$root/venv/bin/python" scripts/eval_judge_valid.py \
  --input "$root/data/guardian-judge-eval-data-v1/$dataset/inputs.csv" \
  --labels-file "$root/data/guardian-judge-eval-data-v1/$dataset/labels.jsonl" \
  --config "$config" --model "$root/models/qwen36-awq" --rates 0.30,0.40 \
  --seconds "$seconds" --out "$root/runs/$job"
status=$?
set -e
printf '%s\n' "$status" > "$root/logs/$job-exitcode.txt"
exit "$status"
