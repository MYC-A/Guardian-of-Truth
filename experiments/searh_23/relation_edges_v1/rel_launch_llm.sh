#!/bin/bash
# LLM arms for the relation-edges research, sequential to avoid 429 storms.
# Phases: det -> cls -> grp -> e2e, for mistral then codestral,
# original suite then renamed suite. Caching makes re-runs cheap.
set -e
cd /workspace/guardian/repos/Guardian-of-Truth/experiments/searh_23/relation_edges_v1
PY=/workspace/guardian/venv/bin/python

for suite in original renamed; do
  for model in mistral codestral; do
    for phase in det cls grp e2e; do
      echo "=== $phase $model $suite ==="
      REL_SUITE=$suite REL_MODEL=$model $PY rel_run_llm.py $phase || echo "PHASE_FAILED $phase $model $suite"
    done
  done
done
echo "ALL LLM ARMS DONE"
