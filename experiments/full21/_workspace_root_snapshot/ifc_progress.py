
import os, json
base = "/mnt/data/guardian/agent-workspace/guardian-repo/outputs/ifc"
for d in sorted(os.listdir(base)):
    rec = os.path.join(base, d, "records.jsonl")
    if os.path.exists(rec):
        n = sum(1 for _ in open(rec))
        print(d, n)
