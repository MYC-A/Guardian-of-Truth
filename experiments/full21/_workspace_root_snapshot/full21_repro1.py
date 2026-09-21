#!/usr/bin/env python3
"""FULL_21 Section 2: reproduce flash granite groundedness full46 control run.

Identical config: model b3421eda, criterion groundedness, max_context_chars 12000,
max_new_tokens 16, transformers backend. Input = public46 (sha 9f6f5fc4...).
"""
import hashlib
import json
import os
import shutil
import subprocess
import time

WT = "/mnt/data/guardian/agent-workspace/Guardian-full21-hybrid"
os.chdir(WT)


def run(cmd, t=120):
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=t)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


out = {}
# 1. copy input + verify sha
src = "/mnt/data/guardian/agent-workspace/guardian-repo/outputs/ifc_valid46_label_free.csv"
os.makedirs("outputs/full21/input", exist_ok=True)
dst = "outputs/full21/input/public46_label_free.csv"
if not os.path.exists(dst):
    shutil.copy2(src, dst)
sha = hashlib.sha256(open(dst, "rb").read()).hexdigest()
out["input_sha"] = sha
out["sha_ok"] = sha == "9f6f5fc496d25e80a008adb589ddcb30fb681d0da131fb83c37fc220c5089e93"

# 2. dry-run first (contract validation, no model)
rc, so, se = run("/mnt/data/guardian/venv/bin/python experiments/full21/run_granite_guardian_flash.py "
                 "--input outputs/full21/input/public46_label_free.csv "
                 "--model-path /mnt/data/guardian/models/granite-guardian-3.3-8b-b3421eda "
                 "--output-dir outputs/research_granite_guardian/full21_control_repro "
                 "--criteria groundedness --max-context-chars 12000 --max-new-tokens 16 --dry-run", t=180)
out["dry_run_rc"] = rc
out["dry_run_out"] = (so + se)[-800:]

print(json.dumps(out, ensure_ascii=False, indent=1))
