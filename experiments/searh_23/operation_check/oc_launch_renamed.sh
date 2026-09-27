#!/bin/bash
# Run the renamed suite for structural arms: B (stanza GPU), C (AMR cpu), D (SRL cpu)
set -u
cd /workspace/guardian/repos/Guardian-of-Truth/experiments/searh_23/operation_check
export OC_OUTPUTS=/workspace/guardian/repos/Guardian-of-Truth/outputs/searh_23/operation_check_v1
export OC_SUITE=renamed
export HF_HOME=/workspace/guardian/hf_cache
LOG=/workspace/guardian/logs

nohup setsid bash -c "cd /workspace/guardian/repos/Guardian-of-Truth/experiments/searh_23/operation_check; exec env OC_SUITE=renamed OC_OUTPUTS=/workspace/guardian/repos/Guardian-of-Truth/outputs/searh_23/operation_check_v1 HF_HOME=/workspace/guardian/hf_cache /workspace/guardian/venv/bin/python -u oc_run_dep.py" >> $LOG/opcheck_B_ren.log 2>&1 < /dev/null &
nohup setsid bash -c "cd /workspace/guardian/repos/Guardian-of-Truth/experiments/searh_23/operation_check; exec env OC_SUITE=renamed OC_OUTPUTS=/workspace/guardian/repos/Guardian-of-Truth/outputs/searh_23/operation_check_v1 /workspace/guardian/venvs/amr_env/bin/python -u oc_run_amr.py" >> $LOG/opcheck_C_ren.log 2>&1 < /dev/null &
nohup setsid bash -c "cd /workspace/guardian/repos/Guardian-of-Truth/experiments/searh_23/operation_check; exec env OC_SUITE=renamed OC_OUTPUTS=/workspace/guardian/repos/Guardian-of-Truth/outputs/searh_23/operation_check_v1 /workspace/guardian/venvs/srl_env/bin/python -u oc_run_srl.py" >> $LOG/opcheck_D_ren.log 2>&1 < /dev/null &
echo RENAMED_STRUCTURAL_LAUNCHED
