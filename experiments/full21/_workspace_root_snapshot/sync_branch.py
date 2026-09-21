
import subprocess, json
r = subprocess.run("cd /mnt/data/guardian/agent-workspace/guardian-repo && git pull --ff-only 2>&1 | tail -1 && git log --oneline -1", shell=True, capture_output=True, text=True, timeout=120)
print(r.stdout.strip() or r.stderr.strip())
