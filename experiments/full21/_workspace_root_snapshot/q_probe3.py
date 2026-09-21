
import json
import pandas as pd

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

gold = {r["id"]: int(r["label"]) for _, r in pd.read_parquet(f"{W}/valid.parquet").iterrows()}
p = judges.get("pollinations", {})
b = judges.get("blockrun", {})
common = set(p) & set(b)
dis = [x for x in common if p[x].get("label") != b[x].get("label")]
print("common:", len(common), "disagreements:", len(dis))
right_p = sum(1 for x in dis if p[x]["label"] == gold[x])
right_b = sum(1 for x in dis if b[x]["label"] == gold[x])
print("in disagreements: pollinations right", right_p, "/", len(dis),
      "; blockrun right", right_b, "/", len(dis))
print("dis cases:", dis[:12])
r0 = p.get(dis[0]) if dis else None
if r0:
    print("sample poll record:", json.dumps({k: str(v)[:120] for k, v in r0.items()},
                                             ensure_ascii=False)[:600])
