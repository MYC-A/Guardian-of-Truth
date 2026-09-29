#!/bin/bash
# Re-run the F5 relation-stack arms that failed on the first driver pass
# (builder signature bug, fixed in en_f5_run.py). Resumable per-case.
cd /workspace/guardian/ie_wt/experiments/searh_23/event_normalization_f5
PY=/workspace/guardian/venv/bin/python
LOG=outputs/f5_arms_rerun.log

step() {
  echo "=== [$(date +%H:%M:%S)] START $* ===" >> $LOG
  $PY "$@" >> $LOG 2>&1
  rc=$?
  echo "=== [$(date +%H:%M:%S)] END rc=$rc $* ===" >> $LOG
}

step en_f5_run.py arm v10 f5
step en_f5_run.py arm v11 f5
step en_f5_run.py arm oracleA f5
step en_f5_run.py arm oracleB f5
step en_f5_run.py arm modular f5
echo "=== ARMS_RERUN_COMPLETE $(date +%H:%M:%S) ===" >> $LOG
