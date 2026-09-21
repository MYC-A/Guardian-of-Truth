#!/bin/bash
# superz master chain v2 (session 2) — pollinations serial queue, blockrun cards
PY=/mnt/data/guardian/venv/bin/python
W=/mnt/data/guardian/agent-workspace/Guardian-superz-fullcycle
LOGD=/mnt/data/guardian/agent-workspace
cd $W

echo "[chain2] waiting for E3b blockrun completion (46 OK)..."
for i in $(seq 1 40); do
  N=$($PY -c "import json;print(sum(1 for l in open('outputs/superz_fullcycle/e3b_a1r_live/blockrun/records.jsonl') if json.loads(l).get('status')=='OK'))" 2>/dev/null || echo 0)
  echo "[chain2] e3b done=$N (attempt $i)"
  if [ "$N" -ge 46 ]; then break; fi
  sleep 60
done

echo "[chain2] step 1: e3b_verify (producer dependence, pollinations)"
$PY experiments/superz_fullcycle/e3b_verify.py --provider pollinations > $LOGD/chain_e3bverify.log 2>&1
echo "[chain2] step 1 exit=$?"

echo "[chain2] step 2: a4g (A4 + graph digest)"
$PY experiments/superz_fullcycle/g_graph.py --modes a4g --providers pollinations > $LOGD/chain_a4g.log 2>&1
echo "[chain2] step 2 exit=$?"

echo "[chain2] step 3: gjudge (judge + graph digest)"
$PY experiments/superz_fullcycle/g_graph.py --modes gjudge --providers pollinations > $LOGD/chain_gjudge.log 2>&1
echo "[chain2] step 3 exit=$?"

echo "[chain2] waiting for P cards (blockrun extract, 46 OK)..."
for i in $(seq 1 60); do
  N=$($PY -c "import json;print(sum(1 for l in open('outputs/superz_fullcycle/p_precond/extract_blockrun/cards.jsonl') if json.loads(l).get('status')=='OK'))" 2>/dev/null || echo 0)
  echo "[chain2] cards done=$N (attempt $i)"
  if [ "$N" -ge 46 ]; then break; fi
  sleep 60
done

echo "[chain2] step 4: pjudge (P arm)"
$PY experiments/superz_fullcycle/p_precond.py --modes pjudge --providers pollinations --extract-provider blockrun > $LOGD/chain_pjudge.log 2>&1
echo "[chain2] step 4 exit=$?"

echo "[chain2] step 5: pgjudge (G+P arm)"
$PY experiments/superz_fullcycle/p_precond.py --modes pgjudge --providers pollinations --extract-provider blockrun > $LOGD/chain_pgjudge.log 2>&1
echo "[chain2] step 5 exit=$?"

echo "[chain2] step 6: a4p (A4+cards)"
$PY experiments/superz_fullcycle/a4_pg.py --modes a4p --providers pollinations > $LOGD/chain_a4p.log 2>&1
echo "[chain2] step 6 exit=$?"

echo "[chain2] step 7: a4gp (A4+cards+graph)"
$PY experiments/superz_fullcycle/a4_pg.py --modes a4gp --providers pollinations > $LOGD/chain_a4gp.log 2>&1
echo "[chain2] step 7 exit=$?"

echo "[chain2] DONE"
