#!/usr/bin/env bash
set -euo pipefail
cd /workspace/guardian/repos/Guardian-of-Truth
PY=/workspace/guardian/venv/bin/python
E=experiments/searh_23/event_frontend_level_e
EC=experiments/searh_23/event_canon_v1
export EC_FROZEN="$PWD/$E/frozen"
export EC_OUTPUTS="$PWD/$E/outputs"
"$PY" "$E/le_imperative_rescue.py" e3
"$PY" "$EC/ec_track_b.py" F_pol veto full
"$PY" "$E/le_e3.py" eventness
"$PY" "$E/le_e3.py" corepairs
"$PY" "$E/le_e3.py" assemble
"$PY" "$E/le_fixed_workspace.py"
export EC_TAG=_E EC_MULTISPAN=0
"$PY" "$EC/ec_run_downstream.py" raw
export EC_MULTISPAN=1
"$PY" "$EC/ec_run_downstream.py" oracle
for arm in TRACKB_EVENTNESS_ONLY TRACKB_CANON_F TRACKB_EVENTNESS_CANON_F TRACKB_CANON_B3 TRACKB_EVENTNESS_CANON_B3; do
  "$PY" "$EC/ec_run_downstream.py" canon "$arm"
done
"$PY" "$EC/ec_track_b_score.py"
"$PY" "$EC/ec_downstream_score.py"
export EC_OUTPUTS="$PWD/$E/outputs_fixed"
for arm in TRACKB_FIXED_ONLY TRACKB_FIXED_CANON_F TRACKB_FIXED_EVENTNESS_CANON_F; do
  "$PY" "$EC/ec_run_downstream.py" canon "$arm"
done
"$PY" "$EC/ec_track_b_score.py"
"$PY" "$EC/ec_downstream_score.py"
export EC_OUTPUTS="$PWD/$E/outputs_gold"
"$PY" "$E/le_gold_workspace.py"
"$PY" "$EC/ec_run_downstream.py" oracle
"$PY" "$EC/ec_downstream_score.py"
echo E3_COMPLETE
