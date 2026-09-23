#!/usr/bin/env python3
"""Prepare Q v2 baseline percase CSV (pgjudge labels) + check progress."""
import csv
import json
from pathlib import Path

REPO = Path("/mnt/data/guardian/agent-workspace/Guardian-searh23")
pg = {}
for line in open(REPO / "outputs/big_researh/p_api/pgjudge/records.jsonl", encoding="utf-8"):
    r = json.loads(line)
    pg[r["id"]] = int(r.get("label", 0))

with open(REPO / "outputs/searh_23/q_v2_baseline_pgjudge.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["id", "pred"])
    for cid in sorted(pg):
        w.writerow([cid, pg[cid]])
print(f"written {len(pg)} baseline labels (pgjudge, the arm-A base configuration)")
