#!/usr/bin/env python3
"""FULL_21 recon part 9: secrets perms, ssh, langextract backend, clingo, local mistral Q progress."""
import json
import os

WT = "/mnt/data/guardian/agent-workspace/Guardian-superz-fullcycle"
os.chdir(WT)

out = {}

def sh(cmd, t=25):
    return os.popen(f"timeout {t} " + cmd).read()

out["secrets_ssh_perms"] = sh("ls -ld /mnt/data/guardian/secrets /mnt/data/guardian/ssh 2>&1; ls -la ~/.ssh 2>&1 | head -5")
out["langextract_grounder"] = sh("head -60 experiments/architectures_v2/b_theory/langextract_grounder.py 2>/dev/null")
out["clingo"] = sh("/mnt/data/guardian/venv/bin/python -c 'import clingo; print(\"clingo OK\", clingo.__version__)' 2>&1 | tail -2")
out["langextract_import"] = sh("/mnt/data/guardian/venv/bin/python -c 'import langextract; print(\"langextract OK\", langextract.__version__ if hasattr(langextract,\"__version__\") else \"\")' 2>&1 | tail -2")
out["q_local_log"] = sh("tail -15 /mnt/data/guardian/agent-workspace/q_extract_local.log 2>/dev/null")
out["q_local_out"] = sh("ls outputs/superz_fullcycle/q_discriminate/theory_local/ 2>/dev/null | head; for f in outputs/superz_fullcycle/q_discriminate/theory_local/*.jsonl; do echo \"\$f: \$(wc -l < \\$f) lines\"; done 2>/dev/null | head -5")
out["mistral_env_keys"] = sh("grep -rn 'mistral' experiments/superz_fullcycle/local_llm.py 2>/dev/null | head -10; echo ====; head -50 experiments/superz_fullcycle/local_llm.py 2>/dev/null")
out["third_proc"] = sh("ps auxww | grep 'q_discriminate' | grep -v grep | grep -v pollinations | cut -c1-350")
out["run_mistral_suspicions"] = sh("head -40 experiments/architectures_v2/run_mistral_suspicions.py 2>/dev/null")

print(json.dumps(out, ensure_ascii=False, indent=1))
