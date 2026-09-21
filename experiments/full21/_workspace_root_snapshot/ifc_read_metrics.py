
import json
m = json.load(open("/mnt/data/guardian/agent-workspace/guardian-repo/outputs/baseline_ifc/metrics.json"))
def pick(d, *ks):
    for k in ks:
        d = d[k] if isinstance(d, dict) and k in d else None
        if d is None: return None
    return d
print(json.dumps(m, indent=1)[:1200])
