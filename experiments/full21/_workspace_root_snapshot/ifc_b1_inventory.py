#!/usr/bin/env python3
"""ifc-b1: server-side state inventory (my workspace + shared results, read-only)."""
import json
import os
import subprocess

def run(cmd):
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
    return (p.stdout + (("\n[STDERR] " + p.stderr) if p.returncode != 0 and p.stderr else "")).strip()

out = {}

# 1. My worktree state
out["my_worktree_git"] = run(
    "cd /mnt/data/guardian/agent-workspace/guardian-repo 2>/dev/null && "
    "git rev-parse --abbrev-ref HEAD && git rev-parse --short HEAD && git status --short | head -5 || echo NO_WORKTREE")

# 2. Shared results directory (read-only listing)
out["results_top"] = run("ls -lt /mnt/data/guardian/results/ 2>/dev/null | head -30 || echo NO_RESULTS_DIR")

# 3. Look for A4 / E4 / astra in shared results and other workspaces (read-only find, shallow)
out["a4_hits"] = run(
    "find /mnt/data/guardian/results /mnt/data/guardian/agent-workspace -maxdepth 3 "
    "-iname '*a4*' -o -maxdepth 3 -iname '*astra*' 2>/dev/null | head -20")
out["e4_hits"] = run(
    "find /mnt/data/guardian/results /mnt/data/guardian/agent-workspace -maxdepth 3 "
    "-iname '*e4*' 2>/dev/null | head -20")

# 4. Agent workspaces present (who is working)
out["workspaces"] = run("ls -lt /mnt/data/guardian/agent-workspace/ 2>/dev/null | head -15")

# 5. My outputs on server
out["my_outputs"] = run(
    "ls -la /mnt/data/guardian/agent-workspace/guardian-repo/outputs/ 2>/dev/null | grep -i ifc | head -20; "
    "ls -la /mnt/data/guardian/agent-workspace/guardian-repo/outputs/baseline_ifc/ 2>/dev/null | head -10")

# 6. Running processes of guardian scope
out["procs"] = run("ps aux 2>/dev/null | grep -E 'guardian|python' | grep -v grep | head -15")

# 7. Mistral env presence (existence only, no contents)
out["mistral_env_exists"] = run("ls -la /mnt/data/guardian/secrets/ 2>/dev/null | head -10")

print(json.dumps(out, indent=1, ensure_ascii=False))
