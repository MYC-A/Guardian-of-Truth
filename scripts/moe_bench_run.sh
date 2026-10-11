#!/usr/bin/env bash
# usage: run_bench.sh <name> <repository> [extra server args...]
set -u
name=$1; repo=$2; shift 2
B=/workspace/guardian/moe_bench_20261011
PY=/workspace/guardian/vllm_final_cpu_relocation_20261010/stage/runtime/python/run_python.sh
out=$B/results/$name-$(date +%H%M%S)
cache=$B/cache/$name-$(date +%H%M%S); mkdir -p $cache $B/results
extra=(); for a in "$@"; do extra+=("--extra-server-arg=$a"); done
cd $B/repo
env -u PYTHONPATH HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HOME=$cache/hf XDG_CACHE_HOME=$cache \
  VLLM_CACHE_ROOT=$cache/vllm TRITON_CACHE_DIR=$cache/triton TORCHINDUCTOR_CACHE_DIR=$cache/inductor \
  VLLM_NO_USAGE_STATS=1 DO_NOT_TRACK=1 PYTHONDONTWRITEBYTECODE=1 TMPDIR=/workspace/guardian/tmp \
  $PY scripts/moe_model_bench.py --repository "$repo" --model-dir ${MODEL_DIR:-$B/models/$name} --workers ${WORKERS:-16} --slots ${SLOTS:-16} --python $PY \
  --input valid.parquet --output $out "${extra[@]}"
echo "EXIT $? $out"
