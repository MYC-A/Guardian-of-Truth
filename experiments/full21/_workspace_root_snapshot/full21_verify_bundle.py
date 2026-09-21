#!/usr/bin/env python3
import json
import os
import subprocess

def run(cmd):
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
    return p.returncode, p.stdout.strip(), p.stderr.strip()

out = {}
out["bundle"] = run("ls -la /mnt/data/guardian/results/full21_archive_previous_20260921.bundle 2>&1")
out["sha"] = run("sha256sum /mnt/data/guardian/results/full21_archive_previous_20260921.bundle 2>&1")
out["verify"] = run("git -C /mnt/data/guardian/agent-workspace/Guardian-superz-fullcycle bundle verify /mnt/data/guardian/results/full21_archive_previous_20260921.bundle 2>&1 | tail -2")
out["log"] = run("git -C /mnt/data/guardian/agent-workspace/Guardian-superz-fullcycle log --oneline -3")
print(json.dumps(out, ensure_ascii=False, indent=1))
