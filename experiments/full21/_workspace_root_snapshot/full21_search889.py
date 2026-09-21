#!/usr/bin/env python3
"""FULL_21: broad search for the Guardian OR Granite TP=20 FP=2 F1 .889 reference."""
import json
import os

out = {}

def sh(cmd, t=40):
    return os.popen(f"timeout {t} " + cmd).read()

out["flash_dir"] = sh("ls -la /mnt/data/guardian/agent-workspace/flash-repo/ 2>&1 | head -15")
out["flash_git"] = sh("cd /mnt/data/guardian/agent-workspace/flash-repo && ls -d .git 2>&1; git -C /mnt/data/guardian/agent-workspace/flash-repo log --oneline -10 2>&1 | head -12")

# search all worktrees + results for the OR-Granite .889
out["search_or_granite"] = sh(
    "grep -rn 'OR Granite\\|OR-Granite\\|granite.*OR\\|OR.*granite' --include='*.md' -i /mnt/data/guardian/agent-workspace/*/docs/ /mnt/data/guardian/agent-workspace/*/*.md 2>/dev/null | grep -iv 'binary' | head -25", t=50
)
out["search_fp2"] = sh(
    "grep -rn 'FP=2\\|FP 2\\|FP2 ' --include='*.md' --include='*.json' /mnt/data/guardian/agent-workspace/*/docs/ /mnt/data/guardian/agent-workspace/*/outputs/ /mnt/data/guardian/results/ 2>/dev/null | head -20", t=50
)
out["worklog_tail"] = sh("tail -80 WORKLOG.md 2>/dev/null")
out["exp_matrix_tail"] = sh("tail -50 docs/research/EXPERIMENT_MATRIX.md 2>/dev/null || ls docs/research/ 2>/dev/null")

print(json.dumps(out, ensure_ascii=False, indent=1))
