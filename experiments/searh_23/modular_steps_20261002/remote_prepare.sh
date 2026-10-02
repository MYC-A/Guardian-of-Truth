#!/bin/bash
set -euo pipefail
base=/workspace/guardian
repo=$base/repos/Guardian-of-Truth
checkout=$base/repos/modular-step2-4-worktree
git -C "$repo" fetch origin research/modular-step2-4-20261002
if [ ! -e "$checkout" ]; then
  git -C "$repo" worktree add --detach --no-checkout "$checkout" origin/research/modular-step2-4-20261002
  git -C "$checkout" sparse-checkout set service src experiments/searh_23/three_architectures experiments/searh_23/hybrid_service_v1 experiments/searh_23/system_research_v2 experiments/searh_23/system_integration_v1 experiments/searh_23/modular_steps_20261002 docs/searh_23
  git -C "$checkout" checkout origin/research/modular-step2-4-20261002
fi
test -z "$(git -C "$checkout" status --porcelain)"
mkdir -p "$base/results/modular_steps_20261002"
if [ ! -e "$base/modular_venv/bin/python" ]; then
  "$base/venv/bin/python" -m venv --system-site-packages "$base/modular_venv"
fi
"$base/modular_venv/bin/python" -m pip install --disable-pip-version-check lxml nltk pyyaml simplejson gdown > "$base/results/modular_steps_20261002/dependency_install.log" 2>&1
cd "$checkout"
nohup "$base/modular_venv/bin/python" -u experiments/searh_23/modular_steps_20261002/run_control.py > "$base/results/modular_steps_20261002/control_dev_launcher.log" 2>&1 < /dev/null &
printf '%s\n' "$!" > "$base/results/modular_steps_20261002/control_dev.pid"
printf 'Started pinned control PID %s\n' "$!"
