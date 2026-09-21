
import subprocess, os
repo = "/mnt/data/guardian/agent-workspace/guardian-repo"
# 1. preprocess: build granite function-call rows with tools
r = subprocess.run(["/mnt/data/guardian/venv/bin/python","experiments/offline_guardian/preprocess_granite_function_calls.py","--input","outputs/ifc_valid46_label_free.csv","--output","outputs/ifc/granite_fc_rows_ifc.csv","--trace","outputs/ifc/granite_fc_trace_ifc.json"], capture_output=True, text=True, cwd=repo, timeout=600)
print("preprocess rc:", r.returncode)
print("OUT:", r.stdout[-500:]); print("ERR:", r.stderr[-500:])
# 2. check tools column present
import csv
csv.field_size_limit(2**30)
rows = list(csv.DictReader(open(os.path.join(repo, "outputs/ifc/granite_fc_rows_ifc.csv"))))
print("rows:", len(rows), "cols:", list(rows[0].keys()) if rows else None, "tools nonempty:", sum(1 for x in rows if (x.get("tools") or "").strip()))
