#!/bin/bash
PY=/mnt/data/guardian/venv/bin/python
W=/mnt/data/guardian/agent-workspace/Guardian-superz-fullcycle
cd $W
echo "[q-extract-local] start $(date)"
$PY experiments/superz_fullcycle/q_discriminate.py --modes extract --providers local > /mnt/data/guardian/agent-workspace/q_extract_local.log 2>&1
echo "[q-extract-local] exit=$? $(date)"
