#!/bin/bash
# Mini-suite arms for POST-HOC validation (per S15 honesty rule):
# base arms with frozen prompts (det/cls/grp/e2e mistral + DET_local) +
# the post-hoc DIR arm. Mini gold is not opened before these runs complete.
set -e
cd /workspace/guardian/repos/Guardian-of-Truth/experiments/searh_23/relation_edges_v1
PY=/workspace/guardian/venv/bin/python

echo "=== R_retriever mini ==="
REL_SUITE=mini REL_ARM_DIR=R_retriever $PY rel_run_retriever.py
echo "=== DET_local mini ==="
REL_SUITE=mini REL_ARM_DIR=DET_local $PY rel_run_detector.py
echo "=== det mistral mini ==="
REL_SUITE=mini REL_MODEL=mistral $PY rel_run_llm.py det
echo "=== cls mistral mini ==="
REL_SUITE=mini REL_MODEL=mistral $PY rel_run_llm.py cls
echo "=== grp mistral mini ==="
REL_SUITE=mini REL_MODEL=mistral $PY rel_run_llm.py grp
echo "=== e2e mistral mini ==="
REL_SUITE=mini REL_MODEL=mistral $PY rel_run_llm.py e2e
echo "=== dir mistral mini (post-hoc) ==="
REL_SUITE=mini REL_MODEL=mistral $PY rel_run_llm.py dir
echo "=== dir mistral original (post-hoc, retrospective) ==="
REL_SUITE=original REL_MODEL=mistral $PY rel_run_llm.py dir
echo "=== dir mistral renamed (post-hoc, retrospective) ==="
REL_SUITE=renamed REL_MODEL=mistral $PY rel_run_llm.py dir
echo "ALL MINI ARMS DONE"
