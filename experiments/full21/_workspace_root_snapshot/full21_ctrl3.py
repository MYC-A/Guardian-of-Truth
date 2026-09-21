#!/usr/bin/env python3
"""FULL_21: read flash granite groundedness raw run + evaluator."""
import json
import os
import subprocess

def run(cmd, t=40):
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=t)
    return p.returncode, p.stdout.strip(), p.stderr.strip()

out = {}
G = "/mnt/data/guardian/agent-workspace/guardian-repo/outputs/ifc/research_granite_guardian"
os.chdir(G)

out["ls"] = run("ls -laR . | head -40")
out["manifest"] = run("for f in $(find . -name 'manifest*' -o -name 'run.json' | head -3); do echo \"== $f\"; cat $f | head -40; done")
out["records_head"] = run("for f in $(find . -name '*.jsonl' | head -2); do echo \"== $f\"; head -2 $f | cut -c1-600; done")
out["csv_head"] = run("for f in $(find . -name '*.csv' | head -3); do echo \"== $f\"; head -3 $f | cut -c1-300; done")
out["evaluator"] = run("cat /mnt/data/guardian/agent-workspace/flash-repo/experiments/architectures_v2/ifc_evaluate.py 2>/dev/null | head -80")

print(json.dumps(out, ensure_ascii=False, indent=1))
