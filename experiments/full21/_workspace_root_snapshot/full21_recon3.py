#!/usr/bin/env python3
"""FULL_21 recon part 3: MODEL_API_AUDIT, HANDOFF, q jobs detail, mistral env search."""
import json
import os

WT = "/mnt/data/guardian/agent-workspace/Guardian-superz-fullcycle"
os.chdir(WT)

out = {}

def sh(cmd):
    return os.popen(cmd).read()

out["model_api_audit"] = sh("cat docs/next/MODEL_API_AUDIT.md 2>/dev/null | head -80")
out["mistral_env_search"] = sh(
    "grep -rn 'MISTRAL_API_KEY' --include='*.sh' --include='*.env' --include='*.txt' --include='*.md' /mnt/data/guardian/ 2>/dev/null | grep -v agent-workspace | head -10; "
    "echo '--- wrapper?'; ls -la /mnt/data/guardian/*.sh 2>/dev/null; "
    "echo '--- restore_access.sh:'; cat /mnt/data/guardian/restore_access.sh 2>/dev/null | head -30"
)
out["q_proc_detail"] = sh("ps auxww | grep q_discriminate | grep -v grep | cut -c1-400")
out["q_theory_counts"] = sh(
    "for d in outputs/superz_fullcycle/q_discriminate/theory_*/; do echo \"$d: $(find $d -name '*.json' 2>/dev/null | wc -l) json, $(find $d -name '*.jsonl' 2>/dev/null | wc -l) jsonl\"; done; "
    "echo '---'; find outputs/superz_fullcycle/q_discriminate -type f -mmin -30 | head -10"
)
out["gp_metrics"] = sh(
    "for f in outputs/superz_fullcycle/g_graph/gjudge_blockrun outputs/superz_fullcycle/p_precond/pjudge_blockrun outputs/superz_fullcycle/p_precond/pgjudge_blockrun outputs/superz_fullcycle/gp_combo/a4p_blockrun outputs/superz_fullcycle/gp_combo/a4gp_blockrun outputs/superz_fullcycle/g_graph/a4g_blockrun; do "
    "echo \"== $f\"; ls $f 2>/dev/null | head -6; done"
)
out["a4_baseline_blockrun"] = sh("ls outputs/superz_fullcycle/e4_a34_verify/a4_blockrun/ 2>/dev/null | head; find outputs/superz_fullcycle -maxdepth 3 -name 'run.json' -newer outputs/superz_fullcycle/e9_robustness 2>/dev/null | head")

print(json.dumps(out, ensure_ascii=False, indent=1))
