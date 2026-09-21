
import subprocess, os
os.chdir("/mnt/data/guardian/agent-workspace/guardian-repo")
os.makedirs("outputs/baseline_ifc", exist_ok=True)
r = subprocess.run(["/mnt/data/guardian/venv/bin/python","scripts/predict.py","--input","valid.parquet",
    "--output","outputs/baseline_ifc/predictions.csv","--audit","outputs/baseline_ifc/audit.jsonl"],
    capture_output=True, text=True, timeout=900)
print("predict exit:", r.returncode); print(r.stdout[-1200:]); print(r.stderr[-800:])
r2 = subprocess.run(["/mnt/data/guardian/venv/bin/python","scripts/evaluate.py","--input","valid.parquet",
    "--output","outputs/baseline_ifc/metrics.json"], capture_output=True, text=True, timeout=300)
print("eval exit:", r2.returncode); print(r2.stdout[-1500:]); print(r2.stderr[-600:])
