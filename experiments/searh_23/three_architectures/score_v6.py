#!/usr/bin/env python3
"""Score a V6 run against a gold CSV (official response-level metrics) +
protocol stats (escalation rate, degraded rows, family agreement)."""
import argparse
import csv
import json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pred", required=True)
    ap.add_argument("--gold", required=True)
    ap.add_argument("--audit", required=True)
    args = ap.parse_args()

    pred = {r["id"]: int(r["label"])
            for r in csv.DictReader(open(args.pred))}
    gold = {r["id"]: int(r["label"])
            for r in csv.DictReader(open(args.gold))}

    tp = [c for c in gold if gold[c] == 1 and pred.get(c) == 1]
    fp = [c for c in gold if gold[c] == 0 and pred.get(c) == 1]
    fn = [c for c in gold if gold[c] == 1 and pred.get(c) == 0]
    tn = [c for c in gold if gold[c] == 0 and pred.get(c) == 0]
    p = len(tp) / (len(tp) + len(fp)) if tp or fp else 0.0
    r = len(tp) / (len(tp) + len(fn)) if tp or fn else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    print(f"TP{len(tp)} FP{len(fp)} FN{len(fn)} TN{len(tn)} "
          f"P={p:.4f} R={r:.4f} F1={f1:.4f}")
    print(f"FP: {fp}")
    print(f"FN: {fn}")

    modes = {}
    routing = {}
    fam_votes = {}
    for line in open(args.audit):
        d = json.loads(line)
        modes[d["decision"]["mode"]] = modes.get(d["decision"]["mode"], 0) + 1
        rt = d["decision"].get("routing")
        if rt:
            routing[rt] = routing.get(rt, 0) + 1
        for v in d.get("votes", []):
            if v.get("valid"):
                fam = v["family"]
                fam_votes.setdefault(fam, []).append(v["vote"]["label"])
    print(f"decision modes: {modes}")
    print(f"routing: {routing}")
    for fam, labs in fam_votes.items():
        print(f"family {fam}: {len(labs)} valid votes, "
              f"1s={sum(labs)} ({sum(labs)/len(labs):.0%})")
    stats_path = Path(args.audit).parent / "run_stats.json"
    if stats_path.exists():
        print(f"run_stats: {json.load(open(stats_path))}")


if __name__ == "__main__":
    main()
