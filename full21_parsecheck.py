#!/usr/bin/env python3
import csv
import inspect
import sys

sys.path.insert(0, "src")
from guardian_truth.parsing import parse_events

csv.field_size_limit(2**30)
rows = list(csv.DictReader(open("outputs/full21/input/public46_label_free.csv")))
evs = parse_events(rows[0]["prompt"], "prompt")
print("events:", len(evs))
e = evs[0]
print("type:", type(e).__name__)
print("attrs:", [a for a in dir(e) if not a.startswith("_")][:25])
if hasattr(e, "observations"):
    obs = e.observations
    print("obs0:", obs[0] if obs else None)
    if obs:
        print("obs attrs:", [a for a in dir(obs[0]) if not a.startswith("_")][:15])
# graph digest smoke
sys.path.insert(0, "experiments/superz_fullcycle")
from g_graph import graph_digest
d = graph_digest(rows[0]["prompt"], rows[0]["response"])
print("digest chars:", len(d))
print("--- digest head ---")
print(d[:900])
