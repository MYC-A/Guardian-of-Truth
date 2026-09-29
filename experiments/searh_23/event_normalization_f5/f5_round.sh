#!/bin/bash
# EN F5 single-round inference driver (directive §11: ONE round, all
# pre-registered arms; sequential, resumable - every stage skips existing
# per-case outputs). External baselines + scoring run separately.
cd /workspace/guardian/ie_wt/experiments/searh_23/event_normalization_f5
PY=/workspace/guardian/venv/bin/python
LOG=outputs/f5_round.log
mkdir -p outputs

step() {
  echo "=== [$(date +%H:%M:%S)] START $* ===" >> $LOG
  $PY "$@" >> $LOG 2>&1
  echo "=== [$(date +%H:%M:%S)] END rc=$? $* ===" >> $LOG
}

# ---- F5 main suite
step en_f5_run.py frontend f5
step en_f5_run.py hygiene f5
step en_f5_run.py bnorm f5
step en_f5_run.py arm v10 f5
step en_f5_run.py arm v11 f5
step en_f5_run.py arm oracleA f5
step en_f5_run.py arm oracleB f5

# ---- identity arms (writes f5_modular_decisions.json)
step en_f5_identity.py

# ---- modular architecture (needs identity decisions)
step en_f5_run.py arm modular f5

# ---- rename suite (v10 + v11)
step en_f5_run.py frontend f5r
step en_f5_run.py hygiene f5r
step en_f5_run.py bnorm f5r
step en_f5_run.py arm v10 f5r
step en_f5_run.py arm v11 f5r

# ---- CF twins (frontend chain + node builds; identity checks separate)
step en_f5_run.py frontend cf
step en_f5_run.py hygiene cf
step en_f5_run.py bnorm cf
step en_f5_run.py nodes v10 cf
step en_f5_run.py nodes v11 cf

echo "=== ROUND COMPLETE $(date +%H:%M:%S) ===" >> $LOG
