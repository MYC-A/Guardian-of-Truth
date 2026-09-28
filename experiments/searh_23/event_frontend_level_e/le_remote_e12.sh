#!/usr/bin/env bash
set -euo pipefail
cd /workspace/guardian/repos/Guardian-of-Truth
PY=/workspace/guardian/venv/bin/python
E=experiments/searh_23/event_frontend_level_e
export EC_FROZEN="$PWD/$E/frozen"
export EC_OUTPUTS="$PWD/$E/outputs"
"$PY" "$E/le_eventness.py" run
"$PY" "$E/le_identity.py" cores
"$PY" "$E/le_identity.py" selected
"$PY" "$E/le_imperative_completion.py" e5
"$PY" "$E/le_eventness.py" score
"$PY" "$E/le_identity.py" score
"$PY" "$E/le_train_ce.py" score
"$PY" "$E/le_train_ce_binary.py" score
"$PY" "$E/le_imperative_completion.py" score
echo E12_COMPLETE
