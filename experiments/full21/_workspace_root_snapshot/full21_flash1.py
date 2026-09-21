#!/usr/bin/env python3
"""FULL_21: flash-repo deep dive — the .8889 OR-ensemble implementation."""
import json
import os

out = {}

def sh(cmd, t=40):
    return os.popen(f"timeout {t} " + cmd).read()

F = "/mnt/data/guardian/agent-workspace/flash-repo"
os.chdir(F)

out["branch"] = sh("git branch --show-current; git log -1 --format='%H %ci %s'")
out["exp_tree"] = sh("find experiments -maxdepth 2 -type d | sort | head -30")
out["ifc_files"] = sh("ls experiments/ifc/ 2>/dev/null | head -40")
out["outputs"] = sh("ls outputs/ | head -20; echo ---; ls outputs/ifc* 2>/dev/null | head -30")
out["commit_890435"] = sh("git show --stat 8904a35 2>/dev/null | head -40")
out["docs_recent"] = sh("ls -lt docs/ | head -10; ls docs/research/ 2>/dev/null | head -20")

print(json.dumps(out, ensure_ascii=False, indent=1))
