#!/bin/bash
PY=/mnt/data/guardian/venv/bin/python
W=/mnt/data/guardian/agent-workspace/Guardian-superz-fullcycle
cd $W
echo "[pextract-blockrun] waiting for E3b (46 OK)..."
for i in $(seq 1 40); do
  N=$($PY -c "import json;print(sum(1 for l in open('outputs/superz_fullcycle/e3b_a1r_live/blockrun/records.jsonl') if json.loads(l).get('status')=='OK'))" 2>/dev/null || echo 0)
  echo "[pextract-blockrun] e3b done=$N (attempt $i)"
  if [ "$N" -ge 46 ]; then break; fi
  sleep 60
done
echo "[pextract-blockrun] starting extraction on blockrun"
$PY experiments/superz_fullcycle/p_precond.py --modes extract --providers blockrun > /mnt/data/guardian/agent-workspace/p_extract_blockrun.log 2>&1
echo "[pextract-blockrun] exit=$?"
