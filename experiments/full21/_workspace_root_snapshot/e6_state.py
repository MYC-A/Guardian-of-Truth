
import json
from collections import Counter
W = "/mnt/data/guardian/agent-workspace/Guardian-superz-fullcycle"
try:
    with open(f"{W}/outputs/superz_fullcycle/e6_agenthallu/blockrun/records.jsonl") as f:
        lines = [json.loads(l) for l in f if l.strip()]
    ok = [l for l in lines if l.get("status") == "OK"]
    print(f"E6 records: {len(lines)}, OK: {len(ok)} / 488")
    print("labels:", dict(Counter(l.get("label", "?") for l in ok)))
    ids = {l.get("id") for l in ok}
    print("unique cases:", len(ids))
except Exception as e:
    print("E6 ERR:", e)
