#!/bin/bash
# superz chain3a v3 — G experiments on pollinations with probe-gate
PY=/mnt/data/guardian/venv/bin/python
W=/mnt/data/guardian/agent-workspace/Guardian-superz-fullcycle
LOGD=/mnt/data/guardian/agent-workspace
cd $W

ok_count() {
  $PY -c "import json
try:
    print(sum(1 for l in open('$1') if json.loads(l).get('status')=='OK'))
except Exception:
    print(0)" 2>/dev/null || echo 0
}

probe_ok() {
  $PY -c "
import sys
sys.path.insert(0, 'experiments/superz_fullcycle')
from keyless_client import complete
try:
    r = complete('pollinations', [{'role':'user','content':'Say OK'}], max_tokens=5, temperature=0, use_cache=False, max_attempts=2)
    sys.exit(0)
except Exception:
    sys.exit(1)
" 2>/dev/null
  return $?
}

run_gated() {  # $1=script+args, $2=journal, $3=target, $4=passes, $5=gate_sleep, $6=log
  for i in $(seq 1 $4); do
    N=$(ok_count "$2")
    echo "[gate $i] OK=$N / target $3 $(date)"
    if [ "$N" -ge "$3" ]; then break; fi
    # ждём свободного слота pollinations
    for w in $(seq 1 60); do
      if probe_ok; then echo "[gate $i] probe OK after $w waits $(date)"; break; fi
      sleep $5
    done
    $PY $1 >> $6 2>&1
    echo "[gate $i] run exit=$? OK_now=$(ok_count "$2") $(date)"
  done
}

echo "[chain3a-v3] step 1: e3b_verify (65 suspicions) $(date)"
run_gated "experiments/superz_fullcycle/e3b_verify.py --provider pollinations" \
  "outputs/superz_fullcycle/e4_a34_verify/a4_e3bblockrun_pollinations/verifications.jsonl" \
  62 10 90 "$LOGD/chain3_e3bverify.log"
echo "[chain3a-v3] step 1 done $(date)"

echo "[chain3a-v3] step 2: a4g (A4 + graph digest) $(date)"
run_gated "experiments/superz_fullcycle/g_graph.py --modes a4g --providers pollinations" \
  "outputs/superz_fullcycle/g_graph/a4g_pollinations/verifications.jsonl" \
  62 10 90 "$LOGD/chain3_a4g.log"
echo "[chain3a-v3] step 2 done $(date)"

echo "[chain3a-v3] step 3: gjudge (judge + graph digest) $(date)"
run_gated "experiments/superz_fullcycle/g_graph.py --modes gjudge --providers pollinations" \
  "outputs/superz_fullcycle/g_graph/gjudge_pollinations/records.jsonl" \
  42 10 90 "$LOGD/chain3_gjudge.log"
echo "[chain3a-v3] step 3 done $(date)"

echo "[chain3a-v3] DONE $(date)"
