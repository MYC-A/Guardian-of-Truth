#!/usr/bin/env python3
"""FULL_21 recon part 6: gateway worker source inspection + dsw instance env."""
import json

out = {}

def sh(cmd, t=15):
    return os.popen(f"timeout {t} " + cmd).read()

import os
out["gw_files"] = sh("ls -la /mnt/data/guardian/gateway-system/ | head -20")
out["worker_py"] = sh("head -120 /mnt/data/guardian/gateway-system/worker.py 2>/dev/null")
out["gw_env_keys"] = sh("grep -n 'environ\\|env' /mnt/data/guardian/gateway-system/worker.py 2>/dev/null | head -20")
out["dsw_instance"] = sh("ls /etc/dsw/instance/ 2>/dev/null; find /etc/dsw/instance -maxdepth 2 -type f 2>/dev/null | head -10")

print(json.dumps(out, ensure_ascii=False, indent=1))
