#!/usr/bin/env python3
import json
import os
import subprocess

def run(cmd):
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=180)
    return p.returncode, p.stdout.strip(), p.stderr.strip()

out = {}
D = "/mnt/data/guardian/agent-workspace/superz_artifacts"
os.makedirs(D, exist_ok=True)
B = f"{D}/full21_archive_previous_20260921.bundle"
out["create"] = run(f"git -C /mnt/data/guardian/agent-workspace/Guardian-superz-fullcycle bundle create {B} full_21/archive-previous 2>&1 | tail -2")
out["sha"] = run(f"sha256sum {B} | cut -d' ' -f1")
out["size"] = run(f"stat -c%s {B}")
out["verify"] = run(f"git -C /mnt/data/guardian/agent-workspace/Guardian-superz-fullcycle bundle verify {B} 2>&1 | tail -2")
out["ls"] = run(f"ls -la {D}")
print(json.dumps(out, ensure_ascii=False, indent=1))
