
import json
W = "/mnt/data/guardian/agent-workspace/Guardian-superz-fullcycle"
with open(f"{W}/outputs/superz_fullcycle/e4_a34_verify/a4_pollinations/verifications.jsonl") as f:
    lines = [json.loads(l) for l in f if l.strip()]
ok = [l for l in lines if l.get("status") == "OK"]
from collections import Counter
print(f"records: {len(lines)}, OK: {len(ok)} / 94, verdicts:", dict(Counter(l.get("verdict","FAIL") for l in ok)))
