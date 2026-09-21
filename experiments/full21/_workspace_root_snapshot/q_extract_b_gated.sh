#!/bin/bash
PY=/mnt/data/guardian/venv/bin/python
W=/mnt/data/guardian/agent-workspace/Guardian-superz-fullcycle
cd $W
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
for i in $(seq 1 12); do
  N=$($PY -c "import json
try:
    print(sum(1 for l in open('outputs/superz_fullcycle/q_discriminate/theory_pollinations/records.jsonl') if json.loads(l).get('status')=='OK'))
except Exception:
    print(0)" 2>/dev/null || echo 0)
  echo "[qB pass $i] OK=$N $(date)"
  if [ "$N" -ge 40 ]; then break; fi
  for w in $(seq 1 40); do
    if probe_ok; then break; fi
    sleep 60
  done
  $PY experiments/superz_fullcycle/q_discriminate.py --modes extract --providers pollinations >> /mnt/data/guardian/agent-workspace/q_extract_pollinations.log 2>&1
  echo "[qB pass $i] run exit=$? $(date)"
done
echo "[qB] DONE $(date)"
