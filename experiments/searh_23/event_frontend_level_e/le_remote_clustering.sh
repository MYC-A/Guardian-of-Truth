#!/usr/bin/env bash
set -euo pipefail
cd /workspace/guardian/repos/Guardian-of-Truth
PY=/workspace/guardian/venv/bin/python
E=experiments/searh_23/event_frontend_level_e
EC=experiments/searh_23/event_canon_v1
"$PY" "$E/le_strict_clustering.py"
if [ ! -e "$E/outputs_clustering/_cache" ]; then
  ln -s "$PWD/$E/outputs/_cache" "$E/outputs_clustering/_cache"
fi
export EC_FROZEN="$PWD/$E/frozen" EC_OUTPUTS="$PWD/$E/outputs_clustering"
export EC_TAG=_C EC_MULTISPAN=1
for arm in TRACKB_CANON_F_CL TRACKB_CANON_F_CORR TRACKB_EVENTNESS_CANON_F_CL TRACKB_EVENTNESS_CANON_F_CORR; do
  "$PY" "$EC/ec_run_downstream.py" canon "$arm"
done
"$PY" "$EC/ec_track_b_score.py"
"$PY" "$EC/ec_downstream_score.py"
echo CLUSTERING_COMPLETE
