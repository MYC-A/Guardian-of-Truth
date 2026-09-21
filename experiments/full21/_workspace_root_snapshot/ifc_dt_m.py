
import json
m = json.load(open("/mnt/data/guardian/agent-workspace/guardian-repo/outputs/ifc/dual_theory_v1_p/manifest.json"))
print(json.dumps(m, indent=1))
