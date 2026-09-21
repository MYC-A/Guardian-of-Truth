#!/usr/bin/env python3
"""FULL_21: flash granite groundedness runner + raw outputs + git credentials check."""
import json
import os

out = {}

def sh(cmd, t=40):
    return os.popen(f"timeout {t} " + cmd).read()

F = "/mnt/data/guardian/agent-workspace/flash-repo"
os.chdir(F)

out["granite_py"] = sh("find . -name '*granite*.py' -not -path './.git/*' | head -10")
out["granite_outputs"] = sh("find outputs -maxdepth 3 -iname '*granite*' -o -maxdepth 3 -iname '*grounded*' 2>/dev/null | head -20")
out["ifc_history"] = sh("git log --oneline --all | grep -c ifc; git log --format='%h %s' 8904a35~3..8904a35")
out["offline_guardian"] = sh("ls experiments/offline_guardian/ | head -15")
out["git_cred"] = sh("git config --list --show-origin 2>/dev/null | grep -iE 'credential|user' | head -5; ls -la ~/.git-credentials 2>&1; cat .git/config | grep -A3 remote | head -10")
out["ifc_doc2"] = sh("sed -n '100,200p' docs/research/INDEPENDENT_FULLCYCLE_20260920.md 2>/dev/null")

print(json.dumps(out, ensure_ascii=False, indent=1))
