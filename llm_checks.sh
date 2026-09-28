#!/bin/bash
cd /workspace/guardian/step2_wt
PY=/workspace/guardian/venv/bin/python
DS=experiments/searh_23/step2_evidence_v1
OUT=outputs/searh_23/step2_evidence_v1
ENV=/workspace/guardian/secrets/mistral.env
echo "=== rename C (name-sensitive) ==="
$PY experiments/searh_23/step2_evidence.py rename-check --originals $DS/dev.jsonl --renamed $DS/rename_suite.jsonl --arm C_full --env-file $ENV --output $OUT/ren_C.json
echo "=== rename E (name-blind) ==="
$PY experiments/searh_23/step2_evidence.py rename-check --originals $DS/dev.jsonl --renamed $DS/rename_suite.jsonl --arm E_nameblind --env-file $ENV --output $OUT/ren_E.json
echo "=== rename H (name-blind + witness) ==="
$PY experiments/searh_23/step2_evidence.py rename-check --originals $DS/dev.jsonl --renamed $DS/rename_suite.jsonl --arm H_hybrid --env-file $ENV --output $OUT/ren_H.json
echo "=== cf C ==="
$PY experiments/searh_23/step2_evidence.py cf-check --originals $DS/dev.jsonl --cf $DS/cf_suite.jsonl --arm C_full --env-file $ENV --output $OUT/cf_C.json
echo "=== cf E ==="
$PY experiments/searh_23/step2_evidence.py cf-check --originals $DS/dev.jsonl --cf $DS/cf_suite.jsonl --arm E_nameblind --env-file $ENV --output $OUT/cf_E.json
echo "=== cf H ==="
$PY experiments/searh_23/step2_evidence.py cf-check --originals $DS/dev.jsonl --cf $DS/cf_suite.jsonl --arm H_hybrid --env-file $ENV --output $OUT/cf_H.json
echo "=== cf I ==="
$PY experiments/searh_23/step2_evidence.py cf-check --originals $DS/dev.jsonl --cf $DS/cf_suite.jsonl --arm I_contract --env-file $ENV --output $OUT/cf_I.json
echo "LLM_CHECKS_DONE"
