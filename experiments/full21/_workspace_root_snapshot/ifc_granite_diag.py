
import os, subprocess
print("model exists:", os.path.exists("/mnt/data/guardian/models/granite-guardian-3.3-8b"))
print("csv exists:", os.path.exists("outputs/ifc_valid46_label_free.csv"))
r = subprocess.run(["/mnt/data/guardian/venv/bin/python","experiments/offline_guardian/run_granite_guardian.py","--input","outputs/ifc_valid46_label_free.csv","--output-dir","outputs/ifc/research_granite_guardian/full46_ifc","--dry-run"], capture_output=True, text=True, cwd="/mnt/data/guardian/agent-workspace/guardian-repo", timeout=120)
print("dry-run rc:", r.returncode)
print("OUT:", r.stdout[-800:])
print("ERR:", r.stderr[-800:])
