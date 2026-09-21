#!/usr/bin/env python3
"""FULL_21 recon part 8: op_start detail."""
import json
import os

out = {}

def sh(cmd, t=15):
    return os.popen(f"timeout {t} " + cmd).read()

out["op_start"] = sh("grep -n 'def op_start' /mnt/data/guardian/gateway-system/worker.py; sed -n '/def op_start/,/^def op_status/p' /mnt/data/guardian/gateway-system/worker.py | head -80")
out["run_job"] = sh("sed -n '/def run_job/,/^def main/p' /mnt/data/guardian/gateway-system/worker.py | head -70")

print(json.dumps(out, ensure_ascii=False, indent=1))
