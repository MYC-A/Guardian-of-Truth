#!/usr/bin/env python3
"""FULL_21: read run_config + summary of flash granite runs."""
import json
import os
import subprocess

def run(cmd, t=30):
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=t)
    return p.returncode, p.stdout.strip(), p.stderr.strip()

out = {}
G = "/mnt/data/guardian/agent-workspace/guardian-repo/outputs/ifc/research_granite_guardian"

for d in ("full46_ifc", "full46_ctx60k_ifc", "agenthallu_dev_ifc"):
    out[d] = run(f"cat {G}/{d}/run_config.json; echo ---; cat {G}/{d}/summary.json")

# one full record example with prediction field
out["rec_example"] = run(f"head -1 {G}/full46_ifc/records.jsonl | python3 -c 'import json,sys; r=json.load(sys.stdin); print(json.dumps({k:v for k,v in r.items() if k not in (\"raw_model_output\",)}, ensure_ascii=False)[:1200])'")
out["pred_count"] = run(f"grep -c 'prediction' {G}/full46_ifc/records.jsonl; wc -l {G}/full46_ifc/records.jsonl")

print(json.dumps(out, ensure_ascii=False, indent=1))
