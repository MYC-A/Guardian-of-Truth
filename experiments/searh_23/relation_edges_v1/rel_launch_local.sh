#!/bin/bash
# Local-model arms for the relation-edges research: retriever (R1-R4) then
# local detectors (DET-ce / DET-nli), original + renamed suites.
set -e
cd /workspace/guardian/repos/Guardian-of-Truth/experiments/searh_23/relation_edges_v1
PY=/workspace/guardian/venv/bin/python

for suite in original renamed; do
  echo "=== retriever $suite ==="
  REL_SUITE=$suite REL_ARM_DIR=R_retriever $PY rel_run_retriever.py
  echo "=== detector $suite ==="
  REL_SUITE=$suite REL_ARM_DIR=DET_local $PY rel_run_detector.py
done
echo "ALL LOCAL ARMS DONE"
