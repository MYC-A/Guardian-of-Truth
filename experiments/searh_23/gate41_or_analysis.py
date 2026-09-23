#!/usr/bin/env python3
"""SEARCH_23 §2.1: Guardian OR Granite 4.1 from saved (re-run) per-case records.

Combines the structural Guardian per-case predictions (control_repro_percase.csv,
`baseline` column) with the granite-4.1 per-case records at the SAME OR rule as
the old Guardian+3.3 control; compares 3.3 vs 4.1 on identical ids; analyzes
the divergent cases (4.1 standalone vs 3.3 standalone), including which are
already caught by the structural Guardian and what they become in the hybrid.

No new inference: everything from saved per-case records.
Outputs: outputs/searh_23/gate41_or/{percase.csv, divergences.json, summary.json}
"""
import csv
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CONTROL = REPO / "outputs" / "full21" / "control_repro_percase.csv"
G41 = REPO / "outputs" / "research_granite_guardian" / "big_researh_gate41" / "records.jsonl"
OUT = REPO / "outputs" / "searh_23" / "gate41_or"
OUT.mkdir(parents=True, exist_ok=True)

rows = list(csv.DictReader(open(CONTROL)))
g41 = {}
for line in open(G41, encoding="utf-8"):
    r = json.loads(line)
    g41[r["id"]] = 1 if r.get("risk_token") == "yes" else (0 if r.get("risk_token") == "no" else None)

ids = [r["id"] for r in rows if r["id"] in g41]
missing = [r["id"] for r in rows if r["id"] not in g41]


def m(preds):
    tp = fp = fn = tn = 0
    for cid in ids:
        g = int(next(r for r in rows if r["id"] == cid)["gold"])
        p = preds(cid)
        if p is None:
            continue
        tp += p == 1 and g == 1
        fp += p == 1 and g == 0
        fn += p == 0 and g == 1
        tn += p == 0 and g == 0
    P = tp / (tp + fp) if tp + fp else 0
    R = tp / (tp + fn) if tp + fn else 0
    F1 = 2 * P * R / (P + R) if P + R else 0
    return {"TP": tp, "FP": fp, "FN": fn, "TN": tn, "P": round(P, 4),
            "R": round(R, 4), "F1": round(F1, 4), "n": len(ids)}


def col(c):
    return lambda cid: int(float(next(r for r in rows if r["id"] == cid)[c]))


g33 = col("granite_repro")
guard = col("baseline")
g41f = lambda cid: g41.get(cid)
or33 = lambda cid: 1 if (guard(cid) == 1 or g33(cid) == 1) else 0
or41 = lambda cid: 1 if (guard(cid) == 1 or g41f(cid) == 1) else 0

res = {
    "granite_33_standalone": m(g33),
    "granite_41_standalone": m(g41f),
    "guardian_standalone": m(guard),
    "guardian_OR_33": m(or33),
    "guardian_OR_41": m(or41),
    "ids": len(ids), "missing_g41_records": missing,
    "g41_no_score": sum(1 for cid in ids if g41.get(cid) is None),
}

# divergent cases 4.1 vs 3.3 (standalone)
div = []
for r in rows:
    cid = r["id"]
    if cid not in g41 or g41[cid] is None:
        continue
    a, b = g33(cid), g41f(cid)
    if a != b:
        div.append({
            "id": cid, "gold": int(r["gold"]),
            "granite33": a, "granite41": b, "guardian": guard(cid),
            "in_OR_33": or33(cid), "in_OR_41": or41(cid),
            "effect_in_hybrid_41": ("no_change_vs_33_or" if or33(cid) == or41(cid)
                                    else ("new_TP" if or41(cid) == 1 and int(r["gold"]) == 1
                                          else ("new_FP" if or41(cid) == 1 else
                                                ("lost_TP" if or33(cid) == 1 else "changed")))),
        })
res["divergent_41_vs_33"] = div

# per-case csv
with open(OUT / "percase.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["id", "gold", "guardian", "g33", "g41", "or33", "or41"])
    for r in rows:
        cid = r["id"]
        if cid in g41:
            w.writerow([cid, r["gold"], guard(cid), g33(cid),
                        g41f(cid) if g41f(cid) is not None else "",
                        or33(cid), or41(cid)])

(OUT / "summary.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
print(json.dumps(res, ensure_ascii=False, indent=1))
