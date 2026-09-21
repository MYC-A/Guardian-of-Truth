#!/usr/bin/env python3
"""FULL_21 Section 2: compare reproduction vs flash control + compute ensemble."""
import csv
import json

csv.field_size_limit(2**30)

WT = "/mnt/data/guardian/agent-workspace/Guardian-full21-hybrid"
G = "/mnt/data/guardian/agent-workspace/guardian-repo/outputs/ifc/research_granite_guardian"
F = "/mnt/data/guardian/agent-workspace/flash-repo/outputs/ifc"

# my reproduction records
mine = [json.loads(l) for l in open(f"{WT}/outputs/research_granite_guardian/full21_control_repro/records.jsonl", encoding="utf-8")]
p_mine = {r["id"]: (1 if r.get("risk_token") == "yes" else 0) for r in mine}

# flash records (12k control)
flash = [json.loads(l) for l in open(f"{G}/full46_ifc/records.jsonl", encoding="utf-8")]
p_flash = {r["id"]: (1 if r.get("risk_token") == "yes" else 0) for r in flash if r["criterion"] == "groundedness"}

# gold + baseline from flash percase (verified earlier)
gold = {}
base = {}
for row in csv.DictReader(open(f"{F}/percase_v1.csv")):
    gold[row["id"]] = int(row["gold"])
    base[row["id"]] = int(row["baseline"])

# 1. per-case agreement
agree = sum(1 for cid in gold if p_mine.get(cid) == p_flash.get(cid))
mismatch_ids = [cid for cid in gold if p_mine.get(cid) != p_flash.get(cid)]
print(f"per-case agreement: {agree}/{len(gold)}; mismatches: {mismatch_ids}")

# also compare raw risk tokens + statuses
tok_mismatch = [r["id"] for r in mine if r.get("risk_token") != next((f.get("risk_token") for f in flash if f["criterion"] == "groundedness" and f["id"] == r["id"]), None)]
print("risk_token mismatches:", len(tok_mismatch), tok_mismatch[:8])

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
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": round(prec, 4), "recall": round(rec, 4), "f1": round(f1, 4)}

print("granite repro:", json.dumps(metrics(p_mine, gold)))
print("granite flash:", json.dumps(metrics(p_flash, gold)))

# 2. OR ensemble (repro x baseline)
or_ens = {cid: max(base.get(cid, 0), p_mine.get(cid, 0)) for cid in gold}
print("baseline OR granite_repro:", json.dumps(metrics(or_ens, gold)))

# 3. save percase comparison + summary
out_rows = []
for cid in sorted(gold):
    out_rows.append({"id": cid, "gold": gold[cid], "baseline": base[cid],
                     "granite_repro": p_mine.get(cid), "granite_flash": p_flash.get(cid)})
summary = {
    "experiment": "FULL_21 section 2 control reproduction",
    "model": "/mnt/data/guardian/models/granite-guardian-3.3-8b-b3421eda",
    "model_revision": "b3421eda4ba6fc9f9a71121d7e62de08827469a4",
    "criterion": "groundedness",
    "max_context_chars": 12000,
    "max_new_tokens": 16,
    "input_sha256": "9f6f5fc496d25e80a008adb589ddcb30fb681d0da131fb83c37fc220c5089e93",
    "n_cases": 46,
    "per_case_agreement_with_flash": agree,
    "mismatch_ids": mismatch_ids,
    "granite_repro": metrics(p_mine, gold),
    "granite_flash_reference": metrics(p_flash, gold),
    "baseline": metrics(base, gold),
    "ens_baseline_OR_granite_repro": metrics(or_ens, gold),
    "flash_reference_or": {"tp": 20, "fp": 2, "fn": 3, "tn": 21, "f1": 0.8889},
    "repro_run_dir": "outputs/research_granite_guardian/full21_control_repro",
}
with open(f"{WT}/outputs/full21/control_repro_summary.json", "w") as f:
    json.dump(summary, f, indent=1)
with open(f"{WT}/outputs/full21/control_repro_percase.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["id", "gold", "baseline", "granite_repro", "granite_flash"])
    w.writeheader()
    w.writerows(out_rows)
print("saved summary + percase")
print(json.dumps(summary, indent=1))
