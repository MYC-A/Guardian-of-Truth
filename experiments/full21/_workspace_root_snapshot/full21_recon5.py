#!/usr/bin/env python3
"""FULL_21 recon part 5: env keys, .env files, worker environ, bashrc."""
import json
import os

out = {}

def sh(cmd):
    return os.popen(cmd).read()

out["my_env"] = sh("env | grep -iE 'mistral|gemini|gemeni|groq|openrouter|cerebras|api_key|GUARDIAN_' | sed 's/=.*/=<SET>/' | sort")
out["worker_environ"] = sh(
    "for pid in $(pgrep -f 'gateway-system/worker.py' | head -5); do "
    "echo \"-- pid $pid:\"; "
    "tr '\\0' '\\n' < /proc/$pid/environ 2>/dev/null | grep -iE 'mistral|gemini|api_key' | sed 's/=.*/=<SET>/'; done"
)
out["env_files"] = sh(
    "find /mnt/data/guardian -maxdepth 3 -name '.env' -o -maxdepth 3 -name '*.env' 2>/dev/null | head -20"
)
out["env_file_keys"] = sh(
    "for f in $(find /mnt/data/guardian -maxdepth 3 -name '.env' 2>/dev/null | head -10); do "
    "echo \"-- $f:\"; grep -oE '^[A-Za-z_]+=' $f | sort; done"
)
out["bashrc"] = sh("grep -iE 'mistral|secrets|source' ~/.bashrc ~/.profile ~/.bash_profile 2>/dev/null | head -10")
out["ssh_dir"] = sh("ls -la /mnt/data/guardian/ssh 2>&1 | head -5")
out["home"] = sh("ls -la ~ | head -20")
# any wrapper scripts in agent-workspace that source secrets?
out["source_refs"] = sh("grep -rln 'secrets/mistral.env' /mnt/data/guardian/agent-workspace/ 2>/dev/null | head -10")

print(json.dumps(out, ensure_ascii=False, indent=1))
