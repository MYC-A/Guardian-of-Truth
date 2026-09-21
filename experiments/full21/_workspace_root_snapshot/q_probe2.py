
import json
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
            print(prov, len(ok), "OK, keys:", sorted(r.keys())[:12])
    except Exception as e:
        print(prov, "ERR:", e)
import pandas as pd
gold = {r["id"]: int(r["label"]) for _, r in pd.read_parquet(f"{W}/valid.parquet").iterrows()}
p = judges.get("pollinations", {})
b = judges.get("blockrun", {})
common = set(p) & set(b)
dis = [x for x in common if p[x].get("label") != b[x].get("label"))]
print("common:", len(common), "disagreements:", len(dis))
