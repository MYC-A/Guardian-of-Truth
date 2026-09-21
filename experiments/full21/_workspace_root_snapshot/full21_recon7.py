#!/usr/bin/env python3
"""FULL_21 recon part 7: worker exec op detail."""
import json
import os

out = {}

def sh(cmd, t=15):
    return os.popen(f"timeout {t} " + cmd).read()

out["worker_exec"] = sh("sed -n '120,230p' /mnt/data/guardian/gateway-system/worker.py")
out["worker_ops"] = sh("sed -n '440,480p' /mnt/data/guardian/gateway-system/worker.py")

print(json.dumps(out, ensure_ascii=False, indent=1))
