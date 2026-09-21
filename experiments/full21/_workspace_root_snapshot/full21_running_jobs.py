#!/usr/bin/env python3
"""Find running q_discriminate job IDs (full) from worker processes."""
import glob
import json

out = []
import subprocess
r = subprocess.run(["ps", "-eo", "pid,args"], capture_output=True, text=True)
for line in r.stdout.splitlines():
    if "worker.py" in line and "__run" in line:
        parts = line.split()
        pid = parts[0]
        job_id = parts[-1]
        out.append({"pid": pid, "job_id": job_id})
print(json.dumps(out, indent=1))
