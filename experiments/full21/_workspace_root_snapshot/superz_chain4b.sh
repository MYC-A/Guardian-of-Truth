#!/bin/bash
# superz chain4b — P matrix on blockrun (self-consistent pairs) + E9 + E6
PY=/mnt/data/guardian/venv/bin/python
W=/mnt/data/guardian/agent-workspace/Guardian-superz-fullcycle
LOGD=/mnt/data/guardian/agent-workspace
cd $W

echo "[chain4b] step 1: pjudge (P arm, blockrun judge + blockrun cards) $(date)"
$PY experiments/superz_fullcycle/p_precond.py --modes pjudge --providers blockrun --extract-provider blockrun > $LOGD/chain4b_pjudge.log 2>&1
echo "[chain4b] step 1 exit=$? $(date)"

echo "[chain4b] step 2: pgjudge (G+P arm, blockrun) $(date)"
$PY experiments/superz_fullcycle/p_precond.py --modes pgjudge --providers blockrun --extract-provider blockrun > $LOGD/chain4b_pgjudge.log 2>&1
echo "[chain4b] step 2 exit=$? $(date)"

echo "[chain4b] step 3: a4p (A4+cards, blockrun verifier) $(date)"
$PY experiments/superz_fullcycle/a4_pg.py --modes a4p --providers blockrun > $LOGD/chain4b_a4p.log 2>&1
echo "[chain4b] step 3 exit=$? $(date)"

echo "[chain4b] step 4: a4gp (A4+cards+graph, blockrun verifier) $(date)"
$PY experiments/superz_fullcycle/a4_pg.py --modes a4gp --providers blockrun > $LOGD/chain4b_a4gp.log 2>&1
echo "[chain4b] step 4 exit=$? $(date)"

echo "[chain4b] step 5: e9-robustness (blockrun judge) $(date)"
$PY experiments/superz_fullcycle/e9_robustness.py --provider blockrun > $LOGD/chain4b_e9.log 2>&1
echo "[chain4b] step 5 exit=$? $(date)"

echo "[chain4b] step 6: e6-agenthallu completion (blockrun) $(date)"
$PY experiments/superz_fullcycle/e6_agenthallu.py --provider blockrun > $LOGD/chain4b_e6.log 2>&1
echo "[chain4b] step 6 exit=$? $(date)"

echo "[chain4b] DONE $(date)"
