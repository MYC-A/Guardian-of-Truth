#!/usr/bin/env python3
"""FULL_21 recon: server state, jobs, worktrees, branches, results, secrets access check."""
import json
import os

os.chdir("/mnt/data/guardian/agent-workspace")

out = {}

def sh(cmd):
    return os.popen(cmd).read()

out["whoami"] = sh("whoami; id -u")
out["uptime"] = sh("uptime; nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader")

# running processes of interest
out["procs"] = sh("ps aux | grep -E 'python|clingo' | grep -v grep | cut -c1-160 | head -30")

# my worktree
out["wt"] = sh("ls -d */ 2>/dev/null | head -20")
out["superz_wt"] = sh("cd Guardian-superz-fullcycle 2>/dev/null && git log --oneline -8 && git status -sb | head -10 && echo '--- results:' && ls experiments/superz_fullcycle/ 2>/dev/null | head -40")

# server repo branches
out["branches"] = sh("cd /mnt/data/guardian/Guardian-of-Truth 2>/dev/null && git branch -a | head -40 && echo '---' && git log --oneline -5")

# results dir
out["results"] = sh("ls /mnt/data/guardian/results/ 2>/dev/null | head -20")

# secrets access (existence only, no values)
out["secrets"] = sh("ls -la /mnt/data/guardian/secrets/ 2>&1 | head -10")

# models
out["models"] = sh("ls /mnt/data/guardian/models/ 2>/dev/null")

# jobs dir / gateway job registry if visible
out["tmp"] = sh("ls /mnt/data/guardian/ 2>/dev/null")

print(json.dumps(out, ensure_ascii=False, indent=1))
