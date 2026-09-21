#!/usr/bin/env python3
"""FULL_21 sec.2: recover flash granite groundedness run config — raw outputs, input SHA, invocation."""
import json
import os
import subprocess

def run(cmd, cwd=None, t=40):
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=t, cwd=cwd)
    return p.returncode, p.stdout.strip(), p.stderr.strip()

out = {}
F = "/mnt/data/guardian/agent-workspace/flash-repo"
os.chdir(F)

out["outputs_flash"] = run("ls -la outputs/flash/ 2>/dev/null | head -25")
out["predictions_csv"] = run("head -5 outputs/ifc/predictions.csv; wc -l outputs/ifc/predictions.csv")
out["valid46_sha"] = run("sha256sum outputs/ifc/valid46_label_free.csv")
out["valid46_head"] = run("head -c 300 outputs/ifc/valid46_label_free.csv")
out["public46_locate"] = run("find /mnt/data/guardian -maxdepth 4 -name '*.csv' -path '*public*' 2>/dev/null | head -5; ls /mnt/data/guardian/Guardian-research-d4baa86/outputs/research_mistral_base_20260920/full46_direct/ 2>/dev/null | head")
# find granite groundedness raw records anywhere in flash-repo outputs
out["granite_raw_find"] = run("find outputs -type f -name '*.jsonl' | head -20; find outputs -type d | head -30")
# git: how did flash run granite? look for run scripts / manifests in ifc commits
out["git_files_890"] = run("git show 8904a35 --stat --format='' | head -12")
out["s1_manifest"] = run("cat outputs/ifc/s1_blockrun_full46_manifest.json")
# experiments dir for ifc runner scripts
out["ifc_exp"] = run("git show 8904a35:experiments 2>/dev/null | head; git ls-tree 8904a35 experiments/ | head -10")

print(json.dumps(out, ensure_ascii=False, indent=1))
