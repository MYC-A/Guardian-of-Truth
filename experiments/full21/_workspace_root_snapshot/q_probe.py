
import json
from collections import Counter
W = "/mnt/data/guardian/agent-workspace/Guardian-superz-fullcycle"
judges = {}
for prov in ["pollinations", "blockrun", "llm7"]:
    try:
        with open(f"{W}/outputs/superz_fullcycle/e2_a0_cross/{prov}/records.jsonl") as f:
            rows = [json.loads(l) for l in f if l.strip()]
        ok = {r["id"]: r for r in rows if r.get("status") == "OK"}
        judges[prov] = ok
        if ok:
            r = next(iter(ok.values()))
            print(f"[{prov}] {len(ok)} OK, keys: {sorted(r.keys())[:12]) if False else sorted(r.keys())[:12]}")
    except Exception as e:
        print(f"[{prov}] ERR: {e}")
# несогласия pollinations vs blockrun
p, b = judges.get("pollinations", {}), judges.get("blockrun", {})
common = set(p) & set(b)
dis = [c for c in common if p[c].get("label") != b[c].get("label")]
agree = [c for c in common if p[c].get("label") == b[c].get("label")]
print(f"\ncommon cases: {len(common)}, disagreements: {len(dis)}, agreements: {len(agree)}")
gold = {}
import pandas as pd
gold = {r["id"]: int(r["label"]) for _, r in pd.read_parquet(f"{W}/valid.parquet").iterrows()}
right_p = sum(1 for c in dis if p[c]["label"] == gold[c])
right_b = sum(1 for c in dis if b[c]["label"] == gold[c])
print(f"in disagreements: pollinations right {right_p}/{len(dis)}, blockrun right {right_b}/{len(dis)}")
print("disagreement cases:", dis[:12])
