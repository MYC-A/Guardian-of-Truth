#!/usr/bin/env python3
"""FULL_21: docs sweep — manual/, handoff, experiment matrix, flash branch, .889 search."""
import json
import os

out = {}

def sh(cmd, t=30):
    return os.popen(f"timeout {t} " + cmd).read()

WT = "/mnt/data/guardian/agent-workspace/Guardian-superz-fullcycle"
os.chdir(WT)

out["manual_ls"] = sh("find manual -type f | head -30")
out["flash_log"] = sh("cd /mnt/data/guardian/agent-workspace/flash-repo && git log --oneline -15 2>/dev/null && git status -sb 2>/dev/null | head -3")
out["flash_branches"] = sh("cd /mnt/data/guardian/agent-workspace/flash-repo && git branch -a 2>/dev/null | head -15")
out["search_889"] = sh(
    "grep -rn '0\\.889\\|\\.889\\|TP=20, FP=2\\|TP20 FP2\\|TP=20 FP=2' --include='*.md' --include='*.json' --include='*.csv' docs/ experiments/ outputs/ 2>/dev/null | grep -v Binary | head -20", t=60
)
out["search_889_flash"] = sh(
    "cd /mnt/data/guardian/agent-workspace/flash-repo && grep -rn '0\\.889\\|\\.889\\|TP=20' --include='*.md' --include='*.json' docs/ experiments/ outputs/ 2>/dev/null | head -10", t=60
)
out["all_branch_heads"] = sh(
    "git for-each-ref --sort=-committerdate refs/remotes --format='%(refname:short) %(objectname:short) %(committerdate:short) %(subject)' 2>/dev/null | head -20"
)
out["handoff_head"] = sh("head -60 docs/research/HANDOFF_CURRENT_20260920.md 2>/dev/null")

print(json.dumps(out, ensure_ascii=False, indent=1))
