#!/bin/bash
# POLICY_LICENSED_v1 arms launcher.
# Stages (sequential; caching makes re-runs cheap):
#   pairs   : local GPU pair signals (original + renamed)
#   smoke   : ONE mistral call per phase to validate prompt/JSON formats
#   llm     : all mistral phases on original, then renamed core phases
#   codestral: strong-LLM check (det + listwise, original)
# Usage: bash pl_launch.sh [pairs|smoke|llm|codestral|all]
set -u
cd /workspace/guardian/repos/Guardian-of-Truth/experiments/searh_23/policy_licensing_v1
PY=/workspace/guardian/venv/bin/python
export MISTRAL_API_KEY=$(grep -oP '(?<=MISTRAL_API_KEY=).*' /workspace/guardian/secrets/mistral.env | tr -d '"' | tr -d "'")

stage="${1:-all}"

run_pairs () {
  echo "=== pair signals original ==="
  PL_SUITE=original $PY pl_run_pairs.py || echo FAILED_pairs_original
  echo "=== pair signals renamed ==="
  PL_SUITE=renamed $PY pl_run_pairs.py || echo FAILED_pairs_renamed
}

run_smoke () {
  echo "=== smoke: one call per phase (mistral) ==="
  $PY - <<'EOF'
import os, sys
sys.path.insert(0, '.')
from pl_common import MODELS, Mistral, load_suite, out_dir
from pl_run_llm import (SYSTEM, det_user, listwise_user, ev_user, evjudge_user,
                        qa_user, dir_user, cls_user)
from pathlib import Path
client = Mistral(model=MODELS["mistral"], cache_dir=out_dir("_cache"))
case = load_suite("original")[6]  # val_sawmill
ev = {e["eid"]: e for e in case["events"]}
a, b, c = ev["A"], ev["B"], ev["C"]
for name, user in [
    ("det", det_user(case, a, b)),
    ("listwise", listwise_user(case, a, [b, c, ev["D"]])),
    ("ev", ev_user(case, a, b)),
    ("evjudge", evjudge_user(a, b, "An inspected blade guard is required before ripping oak beams.")),
    ("qa", qa_user(case, a)),
    ("dir", dir_user(case, a, b)),
    ("cls", cls_user(case, a, b)),
]:
    rec = client.ask(SYSTEM, user, max_tokens=320)
    ans, err = Mistral.parse_json(rec["raw"])
    print(f"[{name}] err={err} -> {str(ans)[:140]}")
EOF
}

run_llm () {
  for phase in det det_pol det_tool listwise ev evjudge qa dir cls; do
    echo "=== mistral $phase original ==="
    PL_SUITE=original PL_MODEL=mistral $PY pl_run_llm.py $phase || echo "FAILED $phase mistral original"
  done
  for phase in det listwise qa; do
    echo "=== mistral $phase renamed ==="
    PL_SUITE=renamed PL_MODEL=mistral $PY pl_run_llm.py $phase || echo "FAILED $phase mistral renamed"
  done
}

run_codestral () {
  for phase in det listwise; do
    echo "=== codestral $phase original ==="
    PL_SUITE=original PL_MODEL=codestral $PY pl_run_llm.py $phase || echo "FAILED $phase codestral"
  done
}

case "$stage" in
  pairs) run_pairs ;;
  smoke) run_smoke ;;
  llm) run_llm ;;
  codestral) run_codestral ;;
  all) run_pairs; run_smoke; run_llm; run_codestral ;;
  *) echo "usage: $0 [pairs|smoke|llm|codestral|all]"; exit 2 ;;
esac
echo "STAGE $stage DONE"
