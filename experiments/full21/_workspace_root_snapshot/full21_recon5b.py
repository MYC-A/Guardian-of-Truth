#!/usr/bin/env python3
"""FULL_21 recon part 5b: env keys, worker environ (fast only)."""
import json
import os

out = {}

def sh(cmd, t=20):
    return os.popen(f"timeout {t} " + cmd).read()

out["my_env"] = sh("env | grep -iE 'mistral|gemini|gemeni|groq|openrouter|cerebras|api_key|GUARDIAN_' | sed 's/=.*/=<SET>/' | sort")
out["worker_environ"] = sh(
    "for pid in $(pgrep -f 'gateway-system/worker.py' | head -5); do "
    "echo \"-- pid $pid:\"; "
    "tr '\\0' '\\n' < /proc/$pid/environ 2>/dev/null | grep -iE 'mistral|gemini|api_key' | sed 's/=.*/=<SET>/'; done"
)
out["env_files"] = sh("ls -la /mnt/data/guardian/agent-workspace/*/.env /mnt/data/guardian/*/.env /mnt/data/guardian/agent-workspace/.env 2>/dev/null")
out["supervisor_env"] = sh("tr '\\0' '\\n' < /proc/180/environ 2>/dev/null | grep -iE 'mistral|gemini|api' | sed 's/=.*/=<SET>/' | head", t=10)
out["dsw_env"] = sh("ls /etc/dsw 2>/dev/null; cat /etc/environment 2>/dev/null | grep -iE 'mistral|api' | sed 's/=.*/=<SET>/' | head -5", t=10)

print(json.dumps(out, ensure_ascii=False, indent=1))
