#!/bin/bash
# superz chain3b — P experiments on pollinations with probe-gate
# (cards от blockrun готовы; verifier/judge = pollinations для сравнимости с A4/E2)
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

run_gated() {
  for i in $(seq 1 $4); do
    N=$(ok_count "$2")
    echo "[gate $i] OK=$N / target $3 $(date)"
    if [ "$N" -ge "$3" ]; then break; fi
    for w in $(seq 1 60); do
      if probe_ok; then echo "[gate $i] probe OK after $w waits $(date)"; break; fi
      sleep $5
    done
    $PY $1 >> $6 2>&1
    echo "[gate $i] run exit=$? OK_now=$(ok_count "$2") $(date)"
  done
}

echo "[chain3b] step 1: pjudge (P arm, pollinations) $(date)"
run_gated "experiments/superz_fullcycle/p_precond.py --modes pjudge --providers pollinations --extract-provider blockrun" \
  "outputs/superz_fullcycle/p_precond/pjudge_pollinations/records.jsonl" \
  42 10 90 "$LOGD/chain3b_pjudge.log"
echo "[chain3b] step 1 done $(date)"

echo "[chain3b] step 2: pgjudge (G+P arm, pollinations) $(date)"
run_gated "experiments/superz_fullcycle/p_precond.py --modes pgjudge --providers pollinations --extract-provider blockrun" \
  "outputs/superz_fullcycle/p_precond/pgjudge_pollinations/records.jsonl" \
  42 10 90 "$LOGD/chain3b_pgjudge.log"
echo "[chain3b] step 2 done $(date)"

echo "[chain3b] step 3: a4p (A4+cards, pollinations) $(date)"
run_gated "experiments/superz_fullcycle/a4_pg.py --modes a4p --providers pollinations" \
  "outputs/superz_fullcycle/gp_combo/a4p_pollinations/verifications.jsonl" \
  62 10 90 "$LOGD/chain3b_a4p.log"
echo "[chain3b] step 3 done $(date)"

echo "[chain3b] step 4: a4gp (A4+cards+graph, pollinations) $(date)"
run_gated "experiments/superz_fullcycle/a4_pg.py --modes a4gp --providers pollinations" \
  "outputs/superz_fullcycle/gp_combo/a4gp_pollinations/verifications.jsonl" \
  62 10 90 "$LOGD/chain3b_a4gp.log"
echo "[chain3b] step 4 done $(date)"

echo "[chain3b] DONE $(date)"
