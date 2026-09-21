
import subprocess
r = subprocess.run(["/mnt/data/guardian/venv/bin/pip","install","-e",".","--quiet","--no-input"],
    capture_output=True, text=True, cwd="/mnt/data/guardian/agent-workspace/guardian-repo", timeout=900)
print("pip exit:", r.returncode)
print(r.stdout[-2000:]); print(r.stderr[-2000:])
r = subprocess.run(["/mnt/data/guardian/venv/bin/python","-c","import guardian_truth; print('guardian_truth OK')"], capture_output=True, text=True)
print("import:", r.stdout.strip() or r.stderr.strip()[:300])
