#!/bin/bash
# Launch all LLM arms for a suite in properly detached background processes.
# Usage: oc_launch_llm.sh <original|renamed>
set -u
SUITE="${1:-original}"
cd /workspace/guardian/repos/Guardian-of-Truth/experiments/searh_23/operation_check
export OC_OUTPUTS=/workspace/guardian/repos/Guardian-of-Truth/outputs/searh_23/operation_check_v1
export OC_SUITE="$SUITE"
LOG=/workspace/guardian/logs
PY=/workspace/guardian/venv/bin/python

nohup setsid env OC_SUITE="$SUITE" OC_ARM=A_e2e      $PY oc_run_llm.py >> $LOG/opcheck_A.log 2>&1 < /dev/null &
nohup setsid env OC_SUITE="$SUITE" OC_ARM=A2_pairs   $PY oc_run_llm.py >> $LOG/opcheck_A2.log 2>&1 < /dev/null &
nohup setsid env OC_SUITE="$SUITE" OC_ARM=relation   $PY oc_run_llm.py >> $LOG/opcheck_rel.log 2>&1 < /dev/null &
nohup setsid env OC_SUITE="$SUITE" OC_ARM=I_e2e      $PY oc_run_llm.py >> $LOG/opcheck_I.log 2>&1 < /dev/null &
nohup setsid env OC_SUITE="$SUITE" OC_ARM=I2_pairs   $PY oc_run_llm.py >> $LOG/opcheck_I2.log 2>&1 < /dev/null &
nohup setsid env OC_SUITE="$SUITE" OC_ARM=relation_strong $PY oc_run_llm.py >> $LOG/opcheck_rels.log 2>&1 < /dev/null &
echo "LLM_ARMS_LAUNCHED $SUITE"
