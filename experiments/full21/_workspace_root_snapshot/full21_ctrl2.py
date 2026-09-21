#!/usr/bin/env python3
"""FULL_21: locate granite groundedness raw run + ifc runner scripts + flash activity."""
import json
import os
import subprocess

def run(cmd, t=40):
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=t)
    return p.returncode, p.stdout.strip(), p.stderr.strip()

out = {}
F = "/mnt/data/guardian/agent-workspace/flash-repo"
os.chdir(F)

# 1. granite groundedness raw run anywhere on server
out["granite_ns"] = run("find /mnt/data/guardian -maxdepth 5 -type d -name 'research_granite_guardian*' 2>/dev/null | head -10", t=60)
out["granite_ground_dirs"] = run("find /mnt/data/guardian -maxdepth 6 -type d -iname '*grounded*' 2>/dev/null | head -10", t=60)

# 2. ifc runner scripts location
out["ifc_runner_commit"] = run("git show 9248327 --stat --format='' 2>/dev/null | head -15")
out["ifc_eval_commit"] = run("git show c1d9f8c --stat --format='' 2>/dev/null | head -15")

# 3. flash current activity (jobs today)
out["flash_recent"] = run("ls -lt /mnt/data/guardian/agent-workspace/flash-repo/outputs/flash/ | head -8")
out["flash_running"] = run("ps aux | grep -iE 'flash' | grep -v grep | head -5")

print(json.dumps(out, ensure_ascii=False, indent=1))
