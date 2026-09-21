#!/bin/bash
# superz chain5 — Q experiment pipeline + E9 + E6 completion
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

# 1. Q: theory B (pollinations) — gated
echo "[chain5] q-extract theory B (pollinations) $(date)"
run_gated "experiments/superz_fullcycle/q_discriminate.py --modes extract --providers pollinations" \
  "outputs/superz_fullcycle/q_discriminate/theory_pollinations/records.jsonl" \
  42 10 90 "$LOGD/chain5_qextract.log"
echo "[chain5] q-extract done $(date)"

# 2. Q: diff (механический)
echo "[chain5] q-diff $(date)"
$PY experiments/superz_fullcycle/q_discriminate.py --modes diff > $LOGD/chain5_qdiff.log 2>&1
echo "[chain5] q-diff exit=$? $(date)"

# 3. Q: answer (локальные granite+NLI чекеры, GPU)
echo "[chain5] q-answer (local checkers) $(date)"
$PY experiments/superz_fullcycle/q_discriminate.py --modes answer > $LOGD/chain5_qanswer.log 2>&1
echo "[chain5] q-answer exit=$? $(date)"

# 4. Q: repair (механический, integrity-проверка)
echo "[chain5] q-repair $(date)"
$PY experiments/superz_fullcycle/q_discriminate.py --modes repair > $LOGD/chain5_qrepair.log 2>&1
echo "[chain5] q-repair exit=$? $(date)"

# 5. Q: verdict (blockrun, 4 конфигурации, gated по blockrun-ошибкам не нужен — ретраи внутри)
echo "[chain5] q-verdict (blockrun) $(date)"
$PY experiments/superz_fullcycle/q_discriminate.py --modes verdict --verdict-provider blockrun > $LOGD/chain5_qverdict.log 2>&1
echo "[chain5] q-verdict exit=$? $(date)"

# 6. Q: analysis
echo "[chain5] q-analysis $(date)"
$PY experiments/superz_fullcycle/q_discriminate.py --modes analysis > $LOGD/chain5_qanalysis.log 2>&1
echo "[chain5] q-analysis exit=$? $(date)"

# 7. E9 robustness (blockrun judge, 12 кейсов × perturbations)
echo "[chain5] e9-robustness (blockrun) $(date)"
$PY experiments/superz_fullcycle/e9_robustness.py --provider blockrun > $LOGD/chain5_e9.log 2>&1
echo "[chain5] e9 exit=$? $(date)"

# 8. E6 agenthallu completion (blockrun)
echo "[chain5] e6-agenthallu completion (blockrun) $(date)"
$PY experiments/superz_fullcycle/e6_agenthallu.py --provider blockrun > $LOGD/chain5_e6.log 2>&1
echo "[chain5] e6 exit=$? $(date)"

echo "[chain5] DONE $(date)"
