#!/usr/bin/env python3
import csv
import json
import sys

sys.path.insert(0, "src")
from guardian_truth.parsing import parse_events

csv.field_size_limit(2**30)
rows = list(csv.DictReader(open("outputs/full21/input/public46_label_free.csv")))
evs = parse_events(rows[0]["prompt"], "prompt")
for e in evs[:4] + evs[-4:]:
    v = json.dumps(getattr(e, "value", None), ensure_ascii=False)[:100] if getattr(e, "value", None) is not None else None
    print(f"kind={e.kind!r} name={e.name!r} role={e.role!r} source={e.source!r} value={v}")
kinds = {}
for e in evs:
    kinds[e.kind] = kinds.get(e.kind, 0) + 1
print("kinds:", kinds)
# response events
revs = parse_events(rows[0]["response"], "response")
print("response events:", [(e.kind, e.name) for e in revs][:6])
