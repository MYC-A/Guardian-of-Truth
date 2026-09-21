#!/usr/bin/env python3
"""FULL_21: verify risk_token->prediction mapping + compute 12k vs 60k ablation metrics."""
import csv
import json

csv.field_size_limit(2**30)

G = "/mnt/data/guardian/agent-workspace/guardian-repo/outputs/ifc/research_granite_guardian"
F = "/mnt/data/guardian/agent-workspace/flash-repo/outputs/ifc"

# 1. flash percase (gold, baseline, granite_grounded, s1)
percase = {}
for row in csv.DictReader(open(f"{F}/percase_v1.csv")):
    percase[row["id"]] = {k: int(v) for k, v in row.items() if k != "id"}
print("percase rows:", len(percase))

# 2. granite records 12k: groundedness subset
recs12 = [json.loads(l) for l in open(f"{G}/full46_ifc/records.jsonl", encoding="utf-8")]
g12 = {r["id"]: r for r in recs12 if r["criterion"] == "groundedness"}
print("groundedness 12k records:", len(g12))

# check mapping: risk_token yes -> prediction 1?
mismatch = 0
for cid, row in percase.items():
    r = g12.get(cid)
    if r is None:
        print("missing rec for", cid)
        continue
    derived = 1 if r.get("risk_token") == "yes" else 0
    if derived != row["granite_grounded"]:
        mismatch += 1
        if mismatch <= 5:
            print(f"MISMATCH {cid}: risk_token={r.get('risk_token')} derived={derived} percase={row['granite_grounded']}")
print("mapping mismatches:", mismatch)

# 3. ctx60k records + metrics
recs60 = [json.loads(l) for l in open(f"{G}/full46_ctx60k_ifc/records.jsonl", encoding="utf-8")]
g60 = {r["id"]: r for r in recs60 if r["criterion"] == "groundedness"}
print("groundedness 60k records:", len(g60))

def metrics(preds, gold):
    tp = fp = fn = tn = 0
    for cid, g in gold.items():
        p = preds.get(cid)
        if p is None:
            continue
        if g == 1 and p == 1:
            tp += 1
        elif g == 0 and p == 1:
            fp += 1
        elif g == 1 and p == 0:
            fn += 1
        else:
            tn += 1
    prec = tp / (tp + fp) if tp + fp else 0
    rec = tp / (tp + fn) if tp + fn else 0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": round(prec, 4), "recall": round(rec, 4), "f1": round(f1, 4)}

gold = {cid: row["gold"] for cid, row in percase.items()}
p12 = {cid: 1 if r.get("risk_token") == "yes" else 0 for cid, r in g12.items()}
p60 = {cid: 1 if r.get("risk_token") == "yes" else 0 for cid, r in g60.items()}
base = {cid: row["baseline"] for cid, row in percase.items()}

print("granite 12k:", json.dumps(metrics(p12, gold)))
print("granite 60k:", json.dumps(metrics(p60, gold)))
print("baseline:", json.dumps(metrics(base, gold)))

# 4. OR ensembles
or12 = {cid: max(base.get(cid, 0), p12.get(cid, 0)) for cid in gold}
or60 = {cid: max(base.get(cid, 0), p60.get(cid, 0)) for cid in gold}
print("baseline OR granite12k:", json.dumps(metrics(or12, gold)))
print("baseline OR granite60k:", json.dumps(metrics(or60, gold)))

# 5. flips 12k vs 60k
flips = [cid for cid in gold if p12.get(cid) != p60.get(cid)]
print("12k vs 60k flips:", len(flips), flips[:10])

# 6. truncation stats
trunc12 = sum(1 for r in g12.values() if r.get("input_truncation", {}).get("applied"))
trunc60 = sum(1 for r in g60.values() if r.get("input_truncation", {}).get("applied"))
print("truncation applied: 12k:", trunc12, "60k:", trunc60)

# 7. evaluator rest (how prediction derived there)
src = open("/mnt/data/guardian/agent-workspace/flash-repo/experiments/architectures_v2/ifc_evaluate.py").read()
print("=== evaluator tail ===")
print(src[-1500:])
