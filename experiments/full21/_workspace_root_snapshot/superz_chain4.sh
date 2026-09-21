#!/bin/bash
# superz chain4 — blockrun-verified G matrix + Q theory extraction
# (pollinations занят другим агентом; эта матрица самосогласована на blockrun:
#  базы: judge-blockrun = E2 .6333; a4-blockrun = новый прогон ниже)
PY=/mnt/data/guardian/venv/bin/python
W=/mnt/data/guardian/agent-workspace/Guardian-superz-fullcycle
LOGD=/mnt/data/guardian/agent-workspace
cd $W

echo "[chain4] step 1: a4-blockrun baseline (A1R suspicions) $(date)"
$PY experiments/superz_fullcycle/e4_verify.py --modes a4 --providers blockrun > $LOGD/chain4_a4blockrun.log 2>&1
echo "[chain4] step 1 exit=$? $(date)"

echo "[chain4] step 2: a4g-blockrun (A4 + graph digest) $(date)"
$PY experiments/superz_fullcycle/g_graph.py --modes a4g --providers blockrun > $LOGD/chain4_a4g.log 2>&1
echo "[chain4] step 2 exit=$? $(date)"

echo "[chain4] step 3: gjudge-blockrun (judge + graph digest) $(date)"
$PY experiments/superz_fullcycle/g_graph.py --modes gjudge --providers blockrun > $LOGD/chain4_gjudge.log 2>&1
echo "[chain4] step 3 exit=$? $(date)"

echo "[chain4] step 4: e3b-verify-blockrun (producer dependence) $(date)"
$PY experiments/superz_fullcycle/e3b_verify.py --provider blockrun > $LOGD/chain4_e3bverify.log 2>&1
echo "[chain4] step 4 exit=$? $(date)"

echo "[chain4] step 5: q-extract theory A (blockrun) $(date)"
$PY experiments/superz_fullcycle/q_discriminate.py --modes extract --providers blockrun > $LOGD/chain4_qextract.log 2>&1
echo "[chain4] step 5 exit=$? $(date)"

echo "[chain4] DONE $(date)"
