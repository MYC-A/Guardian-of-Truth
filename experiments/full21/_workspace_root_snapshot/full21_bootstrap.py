#!/usr/bin/env python3
"""FULL_21: create working worktree + branch full_21/hybrid-research from superz line,
import flash's granite groundedness runner (proven .7805 module)."""
import json
import os
import subprocess

def run(cmd, cwd=None, timeout=180):
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    return p.returncode, p.stdout.strip(), p.stderr.strip()

out = {}
A = "/mnt/data/guardian/agent-workspace"
SRC = f"{A}/Guardian-superz-fullcycle"
WT = f"{A}/Guardian-full21-hybrid"

# 1. new worktree + branch from superz HEAD (archive parent d0d3935)
out["worktree"] = run(f"git -C {SRC} worktree add {WT} -b full_21/hybrid-research d0d3935 2>&1 | tail -2")
out["head"] = run(f"git -C {WT} rev-parse HEAD")
out["branch"] = run(f"git -C {WT} branch --show-current")

# 2. import flash's granite runner (groundedness full46 capable) — proven module
#    flash runner lives on origin/research/flash-20260921: experiments/offline_guardian/run_granite_guardian.py
out["flash_show"] = run(f"git -C {WT} show origin/research/flash-20260921:experiments/offline_guardian/run_granite_guardian.py > /tmp/flash_granite_runner.py 2>/tmp/flash_err.txt; echo rc=$?; head -3 /tmp/flash_err.txt", timeout=60)
out["import"] = run(f"mkdir -p {WT}/experiments/full21 && cp /tmp/flash_granite_runner.py {WT}/experiments/full21/run_granite_guardian_flash.py && wc -l {WT}/experiments/full21/run_granite_guardian_flash.py")

# also import flash's preprocess adapter if the runner depends on it
out["flash_pre"] = run(f"git -C {WT} show origin/research/flash-20260921:experiments/offline_guardian/preprocess_granite_function_calls.py > {WT}/experiments/full21/preprocess_granite_function_calls.py 2>&1; echo rc=$?; wc -l {WT}/experiments/full21/preprocess_granite_function_calls.py")

# 3. check flash's runner CLI signature (how was groundedness full46 invoked?)
out["runner_cli"] = run(f"grep -n 'argparse\\|add_argument\\|def main\\|criterion\\|groundedness\\|function_call' {WT}/experiments/full21/run_granite_guardian_flash.py | head -30")

# 4. initial commit of the imported module
out["commit"] = run(f"cd {WT} && git add experiments/full21/ && git -c user.name='Super Z Agent' -c user.email='agent@guardian.local' commit -m 'full_21: bootstrap hybrid-research from superz line; import flash granite groundedness runner (proven F1 .7805 module, branch research/flash-20260921)' 2>&1 | tail -2")
out["new_head"] = run(f"git -C {WT} rev-parse HEAD")

print(json.dumps(out, ensure_ascii=False, indent=1))
