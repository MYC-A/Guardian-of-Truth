
import json
from collections import Counter
W = "/mnt/data/guardian/agent-workspace/Guardian-superz-fullcycle"
with open(f"{W}/outputs/superz_fullcycle/e4_a34_verify/a4_pollinations/verifications.jsonl") as f:
    lines = [json.loads(l) for l in f if l.strip()]
ok = [l for l in lines if l.get("status") == "OK"]
print(f"A4: {len(ok)}/94 OK, verdicts:", dict(Counter(l.get("verdict") for l in ok)))
with open(f"{W}/outputs/superz_fullcycle/e3b_a1r_live/blockrun/records.jsonl") as f:
    lines = [json.loads(l) for l in f if l.strip()]
ok = [l for l in lines if l.get("status") == "OK"]
print(f"E3b: {len(ok)}/46 OK")
