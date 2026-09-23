#!/usr/bin/env python3
"""P factor analysis (§5.3): fresh pjudge vs pgjudge + s8 clingo analysis (§5.4)."""
import csv
import json
from pathlib import Path

REPO = Path("/mnt/data/guardian/agent-workspace/Guardian-searh23")


def load_recs(p):
    out = {}
    for line in open(p, encoding="utf-8"):
        try:
            r = json.loads(line)
            out[r["id"]] = r
        except Exception:
            pass
    return out


gold = {}
for row in csv.DictReader(open(REPO / "outputs/full21/control_repro_percase.csv")):
    gold[row["id"]] = int(row["gold"])

pj = load_recs(REPO / "outputs/big_researh/p_api/pjudge/records.jsonl")
pg = load_recs(REPO / "outputs/big_researh/p_api/pgjudge/records.jsonl")


def m(recs):
    tp = fp = fn = tn = 0
    for cid in set(recs) & set(gold):
        g, p = gold[cid], int(recs[cid].get("label", 0))
        tp += p == 1 and g == 1
        fp += p == 1 and g == 0
        fn += p == 0 and g == 1
        tn += p == 0 and g == 0
    P = tp / (tp + fp) if tp + fp else 0
    R = tp / (tp + fn) if tp + fn else 0
    F1 = 2 * P * R / (P + R) if P + R else 0
    return {"TP": tp, "FP": fp, "FN": fn, "TN": tn, "P": round(P, 4),
            "R": round(R, 4), "F1": round(F1, 4)}


print("== P factor: fresh pjudge (cards, no graph) vs pgjudge (cards+graph) ==")
mpj, mpg = m(pj), m(pg)
print("pjudge :", json.dumps(mpj))
print("pgjudge:", json.dumps(mpg))

# where do they differ (graph contribution)?
diff = []
for cid in sorted(set(pj) & set(pg) & set(gold)):
    a, b = int(pj[cid].get("label", 0)), int(pg[cid].get("label", 0))
    if a != b:
        diff.append({"id": cid, "gold": gold[cid], "pjudge": a, "pgjudge": b,
                     "graph_flipped_to": b,
                     "effect": ("TP_gained" if b == 1 and gold[cid] == 1 else
                                ("FP_gained" if b == 1 else
                                 ("FP_removed" if a == 1 and gold[cid] == 0 else "TP_lost")))})
print(f"cases where graph digest changed the label: {len(diff)}")
for d in diff[:15]:
    print(" ", json.dumps(d))

# used_graph flag consistency
ug = sum(1 for r in pg.values() if r.get("used_graph"))
print(f"pgjudge used_graph=true: {ug}/{len(pg)}")

print("\n== §5.4 s8 clingo analysis (fresh records) ==")
recs = [json.loads(line) for line in
        open(REPO / "outputs/big_researh/s8_clingo/cards_verified.jsonl")]
n = len(recs)
bound = sum(1 for r in recs if r.get("binding"))
ver = {}
for r in recs:
    ver[r.get("verdict", "unknown")] = ver.get(r.get("verdict", "unknown"), 0) + 1
block = {}
for r in recs:
    b = r.get("blocking_stage")
    if b:
        block[b] = block.get(b, 0) + 1
kinds = {}
for r in recs:
    k = r.get("obligation_kind")
    kinds[k] = kinds.get(k, 0) + 1
print(f"cards: {n}, bound: {bound}, verdicts: {json.dumps(ver)}")
print(f"blocking stages: {json.dumps(block)}")
print(f"obligation kinds: {json.dumps(kinds)}")
# unknown cause split: no-binding vs binding-with-unobservable-premises
unk = [r for r in recs if r.get("verdict") == "unknown"]
no_bind = sum(1 for r in unk if not r.get("binding"))
print(f"unknown verdicts: {len(unk)}; of them no deterministic binding: {no_bind}; "
      f"bound-but-unobservable-premises: {len(unk) - no_bind}")

out = {"pjudge_fresh": mpj, "pgjudge_fresh": mpg,
       "graph_label_changes": diff, "pgjudge_used_graph": ug,
       "s8": {"cards": n, "bound": bound, "verdicts": ver,
              "blocking_stages": block, "obligation_kinds": kinds,
              "unknown_no_binding": no_bind,
              "unknown_bound_unobservable": len(unk) - no_bind}}
(REPO / "outputs/searh_23").mkdir(exist_ok=True)
(REPO / "outputs/searh_23/p_factor.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=1))
print("written outputs/searh_23/p_factor.json")
