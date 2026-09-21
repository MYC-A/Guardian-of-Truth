#!/bin/bash
PY=/mnt/data/guardian/venv/bin/python
W=/mnt/data/guardian/agent-workspace/Guardian-superz-fullcycle
cd $W
echo "[pextract3-blockrun] start $(date)"
$PY experiments/superz_fullcycle/p_precond.py --modes extract --providers blockrun > /mnt/data/guardian/agent-workspace/p_extract_blockrun3.log 2>&1
echo "[pextract3-blockrun] exit=$? $(date)"
