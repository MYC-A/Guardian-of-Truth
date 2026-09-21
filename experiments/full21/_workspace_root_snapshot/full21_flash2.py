#!/usr/bin/env python3
"""FULL_21: flash-repo ensemble report + granite groundedness run details."""
import json
import os

out = {}

def sh(cmd, t=40):
    return os.popen(f"timeout {t} " + cmd).read()

F = "/mnt/data/guardian/agent-workspace/flash-repo"
os.chdir(F)

out["ifc_ls_full"] = sh("ls -la outputs/ifc/")
out["ensemble_report"] = sh("cat outputs/ifc/ensemble_report_v1.json")
out["metrics"] = sh("cat outputs/ifc/metrics.json 2>/dev/null | head -60")
out["percase_head"] = sh("head -8 outputs/ifc/percase_v1.csv")
out["granite_commits"] = sh("git log --oneline --all | grep -i granite | head; git log --oneline -20")
out["flash_exp"] = sh("ls experiments/flash/ | head -30")
out["ifc_doc"] = sh("head -100 docs/research/INDEPENDENT_FULLCYCLE_20260920.md 2>/dev/null")

print(json.dumps(out, ensure_ascii=False, indent=1))
