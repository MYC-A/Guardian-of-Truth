#!/usr/bin/env python3
import json

recs = [json.loads(l) for l in open("outputs/research_granite_guardian/full21_s3_g12k_think_v2/records.jsonl")]
ok = [r for r in recs if r.get("risk_token")]
no = [r for r in recs if not r.get("risk_token")]
yes = sum(1 for r in ok if r["risk_token"] == "yes")
print("ok:", len(ok), "/ 46; no_score:", len(no), "; risk_yes:", yes)
print("gen_chars sample:", [len(r.get("raw_model_output", "")) for r in recs[:5]])
# quick metrics vs gold
import csv
csv.field_size_limit(2**30)
gold, base = {}, {}
for row in csv.DictReader(open("/mnt/data/guardian/agent-workspace/flash-repo/outputs/ifc/percase_v1.csv")):
    gold[row["id"]] = int(row["gold"])
    base[row["id"]] = int(row["baseline"])
preds = {r["id"]: (1 if r["risk_token"] == "yes" else 0) for r in ok}
tp = fp = fn = tn = 0
for cid, g in gold.items():
    p = preds.get(cid)
    if p is None:
        continue
    if g == 1 and p == 1: tp += 1
    elif g == 0 and p == 1: fp += 1
    elif g == 1 and p == 0: fn += 1
    else: tn += 1
prec = tp / (tp + fp) if tp + fp else 0
rec = tp / (tp + fn) if tp + fn else 0
f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0
print(f"think_v2 standalone (n={len(preds)}): TP{tp} FP{fp} FN{fn} TN{tn} F1 {f1:.4f}")
or_preds = {cid: max(base.get(cid, 0), preds.get(cid, 0)) for cid in gold if cid in preds}
tp = fp = fn = tn = 0
for cid, g in gold.items():
    if cid not in or_preds:
        continue
    p = or_preds[cid]
    if g == 1 and p == 1: tp += 1
    elif g == 0 and p == 1: fp += 1
    elif g == 1 and p == 0: fn += 1
    else: tn += 1
prec = tp / (tp + fp) if tp + fp else 0
rec = tp / (tp + fn) if tp + fn else 0
f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0
print(f"think_v2 OR-baseline: TP{tp} FP{fp} FN{fn} TN{tn} F1 {f1:.4f}")
