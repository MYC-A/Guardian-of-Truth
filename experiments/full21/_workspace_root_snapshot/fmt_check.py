
import json
W = "/mnt/data/guardian/agent-workspace/Guardian-superz-fullcycle"
E3 = f"{W}/outputs/superz_fullcycle/e3a_a1r_posthoc/a1r_cases.jsonl"

with open(E3) as f:
    rows = [json.loads(l) for l in f if l.strip()]
print(f"rows: {len(rows)}")
r = rows[0]
print("top keys:", list(r.keys()))
print("suspicions[0]:", json.dumps(r["suspicions"][0], ensure_ascii=False)[:800])
pos = [(x["id"], s) for x in rows for s in x.get("suspicions", []) if s.get("label") == 1]
print(f"positive suspicions total: {len(pos)}")
import collections
print("reason_types:", dict(collections.Counter(s.get("reason_type") for _, s in pos)))
print()
# A4 journal now
with open(f"{W}/outputs/superz_fullcycle/e4_a34_verify/a4_pollinations/verifications.jsonl") as f:
    lines = [json.loads(l) for l in f if l.strip()]
ok = [l for l in lines if l.get("status") == "OK"]
print(f"A4 journal records: {len(lines)}, OK: {len(ok)}")
import collections
print("verdicts:", dict(collections.Counter(l.get("verdict","FAILED") for l in ok)))
