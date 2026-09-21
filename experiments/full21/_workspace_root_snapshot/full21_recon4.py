#!/usr/bin/env python3
"""FULL_21 recon part 4: HANDOFF mistral access, manual/connect_server, q logs, GP metrics."""
import json
import os

out = {}

def sh(cmd):
    return os.popen(cmd).read()

out["handoff_mistral"] = sh(
    "sed -n '20,80p' /mnt/data/guardian/Guardian-research-b-f51f6fd/docs/research/HANDOFF_CURRENT_20260920.md 2>/dev/null"
)
out["connect_server_env"] = sh(
    "sed -n '85,130p' /mnt/data/guardian/Guardian-research-b-f51f6fd/manual/connect_server.md 2>/dev/null; echo '===='; sed -n '175,235p' /mnt/data/guardian/Guardian-research-b-f51f6fd/manual/connect_server.md 2>/dev/null"
)
out["secrets_mount"] = sh(
    "ls -la /mnt/data/guardian/secrets 2>&1; "
    "sudo -n true 2>&1 | head -1; "
    "cat /mnt/data/guardian/secrets/mistral.env 2>&1 | head -1 | sed 's/=.*/=<REDACTED-CHECK-ONLY>/'"
)
out["q_logs"] = sh(
    "tail -5 /mnt/data/guardian/agent-workspace/q_extract_pollinations.log 2>/dev/null; echo '===='; "
    "ls /mnt/data/guardian/agent-workspace/*.log 2>/dev/null; echo '===='; "
    "for f in /mnt/data/guardian/agent-workspace/q_extract*.log; do echo \"-- $f:\"; tail -3 \"$f\" 2>/dev/null; done"
)
out["q_theory_detail"] = sh(
    "cd /mnt/data/guardian/agent-workspace/Guardian-superz-fullcycle && "
    "for d in outputs/superz_fullcycle/q_discriminate/theory_blockrun outputs/superz_fullcycle/q_discriminate/theory_pollinations outputs/superz_fullcycle/q_discriminate/theory_local; do "
    "echo \"== $d\"; find $d -type f | head -5; "
    "for jf in $(find $d -name '*.jsonl' | head -2); do echo \"   $jf: $(wc -l < $jf) lines\"; done; done"
)
out["gp_metric_files"] = sh(
    "cd /mnt/data/guardian/agent-workspace/Guardian-superz-fullcycle && "
    "find outputs/superz_fullcycle/g_graph outputs/superz_fullcycle/p_precond outputs/superz_fullcycle/gp_combo -name '*.json' -o -name '*.csv' -o -name 'run*' | sort | head -30"
)

print(json.dumps(out, ensure_ascii=False, indent=1))
