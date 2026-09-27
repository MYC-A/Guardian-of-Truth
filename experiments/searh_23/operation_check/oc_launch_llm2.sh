#!/bin/bash
# Launch LLM arms in TWO waves of three to respect Mistral rate limits.
# Usage: oc_launch_llm2.sh <original|renamed> <wave1|wave2>
set -u
SUITE="${1:-original}"
WAVE="${2:-wave1}"
cd /workspace/guardian/repos/Guardian-of-Truth/experiments/searh_23/operation_check || exit 9
export OC_OUTPUTS=/workspace/guardian/repos/Guardian-of-Truth/outputs/searh_23/operation_check_v1
LOG=/workspace/guardian/logs
PY=/workspace/guardian/venv/bin/python

run_arm() {
  local arm="$1" logname="$2"
  nohup setsid bash -c "
    echo '=== LAUNCH \$(date -u +%H:%M:%S) $arm suite=$SUITE'
    cd /workspace/guardian/repos/Guardian-of-Truth/experiments/searh_23/operation_check
    exec env OC_SUITE='$SUITE' OC_ARM='$arm' OC_OUTPUTS='$OC_OUTPUTS' '$PY' -u oc_run_llm.py
  " >> "$LOG/opcheck_$logname.log" 2>&1 < /dev/null &
  echo "launched $arm pid=$!"
}

if [ "$WAVE" = "wave1" ]; then
  run_arm A2_pairs A2
  run_arm relation rel
  run_arm I_e2e I
else
  run_arm I2_pairs I2
  run_arm relation_strong rels
  run_arm A_e2e A
fi
echo "WAVE_LAUNCHED $SUITE $WAVE"
