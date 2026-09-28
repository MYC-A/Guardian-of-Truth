#!/usr/bin/env bash
set -euo pipefail
cd /workspace/guardian/repos/Guardian-of-Truth
PY=/workspace/guardian/venv/bin/python
E=experiments/searh_23/event_frontend_level_e
EC=experiments/searh_23/event_canon_v1
export EC_FROZEN="$PWD/$E/frozen"
export EC_OUTPUTS="$PWD/$E/outputs_rescue"
"$PY" "$EC/ec_track_b.py" F_pol veto full
export EC_TAG=_R EC_MULTISPAN=0
"$PY" "$EC/ec_run_downstream.py" raw
export EC_MULTISPAN=1
"$PY" "$EC/ec_run_downstream.py" canon TRACKB_F_pol_veto
"$PY" "$E/le_rescue_gate.py"
"$PY" "$EC/ec_run_downstream.py" canon TRACKB_RESCUE_GATE
"$PY" "$EC/ec_track_b_score.py"
"$PY" "$EC/ec_downstream_score.py"
echo RESCUE_COMPLETE
