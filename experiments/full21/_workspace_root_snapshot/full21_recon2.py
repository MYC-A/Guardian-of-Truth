#!/usr/bin/env python3
"""FULL_21 recon part 2: job outputs, G/P results, mistral access, flash-repo."""
import json
import os

WT = "/mnt/data/guardian/agent-workspace/Guardian-superz-fullcycle"
os.chdir(WT)

out = {}

def sh(cmd):
    return os.popen(cmd).read()

# 1. outputs inventory
out["outputs_tree"] = sh("find outputs/superz_fullcycle -maxdepth 2 -type d | sort | head -60")
out["outputs_files"] = sh("find outputs/superz_fullcycle -maxdepth 2 -type f -newer /mnt/data/guardian/ENVIRONMENT.txt | head -5; echo ---; du -sh outputs/superz_fullcycle/* 2>/dev/null | sort -k2 | head -40")

# 2. q_discriminate progress: check its output files
out["q_out"] = sh("ls -la outputs/superz_fullcycle/q* 2>/dev/null; find outputs -name '*q*' -mmin -90 -exec ls -la {} \\; 2>/dev/null | head")

# 3. G/P/G+P results from chain4/chain4b
out["gp_results"] = sh("ls -la outputs/superz_fullcycle/g_graph/ outputs/superz_fullcycle/p_precond/ outputs/superz_fullcycle/a4_pg/ outputs/superz_fullcycle/gjudge/ outputs/superz_fullcycle/pgjudge/ outputs/superz_fullcycle/pjudge/ outputs/superz_fullcycle/a4g/ 2>/dev/null")

# 4. mistral access research: how did previous agents get it?
out["mistral_results"] = sh("cat /mnt/data/guardian/results/research_list_mistral_models.py 2>/dev/null | head -40; echo '===='; cat /mnt/data/guardian/results/research_second_critic_smoke.py 2>/dev/null | head -40")

# 5. env vars in venv wrapper or ENVIRONMENT.txt
out["env_txt"] = sh("cat /mnt/data/guardian/ENVIRONMENT.txt 2>/dev/null | head -40")

# 6. search for MISTRAL key references in all repos (names only)
out["mistral_refs"] = sh("grep -rl 'MISTRAL_API_KEY\\|mistral.ai\\|api.mistral' --include='*.py' --include='*.sh' --include='*.md' /mnt/data/guardian/agent-workspace/ /mnt/data/guardian/results/ 2>/dev/null | head -20")

# 7. flash-repo state
out["flash"] = sh("cd /mnt/data/guardian/agent-workspace/flash-repo 2>/dev/null && git log --oneline -10 && git status -sb | head -5 && echo '---files:' && ls | head -20")

# 8. guardian-repo state (main shared?)
out["guardian_repo"] = sh("cd /mnt/data/guardian/agent-workspace/guardian-repo 2>/dev/null && git log --oneline -5 && git branch --show-current")

# 9. remote branches in my worktree
out["remote_branches"] = sh("git branch -r | head -30")

print(json.dumps(out, ensure_ascii=False, indent=1))
