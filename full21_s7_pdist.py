#!/usr/bin/env python3
"""Descriptive P(yes) distribution for s7 records by gold class (no threshold tuning)."""
import csv
import json
import statistics

csv.field_size_limit(2**30)
gold = {}
for row in csv.DictReader(open("/mnt/data/guardian/agent-workspace/flash-repo/outputs/ifc/percase_v1.csv")):
    gold[row["id"]] = int(row["gold"])

for kind in ("plain", "graph"):
    recs = [json.loads(l) for l in open(f"outputs/research_granite_guardian/full21_s7_{kind}/records.jsonl")]
    scores = []
    for r in recs:
        p = r.get("probabilistic_score")
        if p is not None:
            scores.append((p, gold.get(r["case_id"]), r.get("producer_label")))
    by_gold = {0: [], 1: []}
    for p, g, pl in scores:
        if g is not None:
            by_gold[g].append(p)
    out = {
        "kind": kind,
        "n_with_score": len(scores),
        "mean_P_yes_gold1": round(statistics.mean(by_gold[1]), 4) if by_gold[1] else None,
        "mean_P_yes_gold0": round(statistics.mean(by_gold[0]), 4) if by_gold[0] else None,
        "median_P_yes_gold1": round(statistics.median(by_gold[1]), 4) if by_gold[1] else None,
        "median_P_yes_gold0": round(statistics.median(by_gold[0]), 4) if by_gold[0] else None,
    }
    print(json.dumps(out))
