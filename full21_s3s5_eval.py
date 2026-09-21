#!/usr/bin/env python3
"""FULL_21: evaluate S3 (modes/context) + S5 (graph) variants vs gold + OR ensembles."""
import csv
import json
from pathlib import Path

csv.field_size_limit(2**30)

WT = Path("/mnt/data/guardian/agent-workspace/Guardian-full21-hybrid")
F = "/mnt/data/guardian/agent-workspace/flash-repo/outputs/ifc"

gold, base = {}, {}
for row in csv.DictReader(open(f"{F}/percase_v1.csv")):
    gold[row["id"]] = int(row["gold"])
    base[row["id"]] = int(row["baseline"])


def metrics(preds, gold):
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
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": round(prec, 4), "recall": round(rec, 4), "f1": round(f1, 4)}


VARIANTS = {
    "g6k": "outputs/research_granite_guardian/full21_s3_g6k",
    "g24k": "outputs/research_granite_guardian/full21_s3_g24k",
    "g12k_think": "outputs/research_granite_guardian/full21_s3_g12k_think",
    "ansrel_12k": "outputs/research_granite_guardian/full21_s3_ansrel",
    "evas_12k": "outputs/research_granite_guardian/full21_s3_evas",
    "ctxrel_12k": "outputs/research_granite_guardian/full21_s3_ctxrel",
    "s5_graph": "outputs/research_granite_guardian/full21_s5_graph",
    "s5_graph_quotes": "outputs/research_granite_guardian/full21_s5_graph_quotes",
    "s5_plain_summary": "outputs/research_granite_guardian/full21_s5_plain_summary",
}

results = {}
percase = {}
for name, d in VARIANTS.items():
    p = WT / d / "records.jsonl"
    if not p.exists():
        results[name] = "NOT_RUN"
        continue
    recs = [json.loads(l) for l in open(p, encoding="utf-8")]
    preds = {}
    for r in recs:
        if r.get("risk_token") is not None:
            preds[r["id"]] = 1 if r["risk_token"] == "yes" else 0
    no_score = sum(1 for r in recs if r.get("risk_token") is None)
    m = metrics(preds, gold)
    m["n"] = len(preds)
    m["no_score_token"] = no_score
    or_m = metrics({cid: max(base.get(cid, 0), preds.get(cid, 0)) for cid in gold}, gold)
    results[name] = {"standalone": m, "or_with_baseline": or_m}
    percase[name] = preds

# references
results["_reference_control_12k"] = {"standalone": {"tp": 16, "fp": 2, "fn": 7, "tn": 21, "f1": 0.7805},
                                     "or_with_baseline": {"tp": 20, "fp": 2, "fn": 3, "tn": 21, "f1": 0.8889}}
results["_reference_flash_60k"] = {"standalone": {"tp": 10, "fp": 0, "fn": 13, "tn": 23, "f1": 0.6061},
                                   "or_with_baseline": {"tp": 18, "fp": 0, "fn": 5, "tn": 23, "f1": 0.878}}

# per-case CSV
cols = ["id", "gold", "baseline"] + [k for k in VARIANTS if k in percase]
with open(WT / "outputs/full21/s3s5_percase.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(cols)
    for cid in sorted(gold):
        row = [cid, gold[cid], base[cid]]
        for k in cols[3:]:
            row.append(percase[k].get(cid, ""))
        w.writerow(row)

(WT / "outputs/full21/s3s5_metrics.json").write_text(json.dumps(results, indent=1))
print(json.dumps(results, indent=1))
