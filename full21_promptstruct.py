#!/usr/bin/env python3
"""FULL_21: inspect public46 prompt structure (role markers, turns)."""
import csv
import json
import re

csv.field_size_limit(2**30)

WT = "/mnt/data/guardian/agent-workspace/Guardian-full21-hybrid"
rows = list(csv.DictReader(open(f"{WT}/outputs/full21/input/public46_label_free.csv", encoding="utf-8")))
print("rows:", len(rows))

r = rows[0]
prompt = r["prompt"]
# markers
markers = sorted(set(re.findall(r"⟦[A-Z_]+⟧", prompt)))
print("markers in case0 prompt:", markers)
# turn-like patterns
for pat in ("USER:", "ASSISTANT:", "TOOL", "user", "assistant"):
    print(f"count '{pat}':", prompt.count(pat))
print("--- response head:", r["response"][:300].replace("\n", "\\n"))
print("--- prompt tail:", prompt[-400:].replace("\n", "\\n"))
# check all rows for marker consistency
allm = set()
for row in rows:
    allm |= set(re.findall(r"⟦[A-Z_]+⟧", row["prompt"]))
print("all markers across 46:", sorted(allm))
