#!/usr/bin/env python3
"""IFC evaluator — per-case metrics + ensembles (postfix: ifc).

Joins any number of IFC record files (records.jsonl) with gold labels and
computes confusion/F1 per system, plus OR/AND/majority ensembles and
per-domain breakdowns. Also supports plain CSV predictions (id,prediction).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_predictions(path: str) -> dict:
    """Return {id: prediction}. Supports records.jsonl and prediction CSVs."""
    p = Path(path)
    preds = {}
    if p.suffix == ".jsonl" or p.name.endswith("records.jsonl"):
        for line in open(p, encoding="utf-8"):
            rec = json.loads(line)
            if rec.get("prediction") is not None:
                preds[rec["id"]] = int(rec["prediction"])
    elif p.suffix == ".csv":
        import csv
        csv.field_size_limit(min(2 ** 31 - 1, 2 ** 30))
        for row in csv.DictReader(open(p, encoding="utf-8")):
            col = "prediction" if "prediction" in row else ("label" if "label" in row else "pred")
            if row.get(col) not in (None, ""):
                preds[row["id"]] = int(row[col])
    else:
        raise ValueError(f"unsupported predictions file: {p}")
    return preds


def confusion(gold: dict, preds: dict) -> dict:
    tp = fp = fn = tn = 0
    errors = []
    for cid, g in gold.items():
        p = preds.get(cid)
        if p is None:
            continue
        if g == 1 and p == 1: tp += 1
        elif g == 0 and p == 1:
            fp += 1; errors.append(cid)
        elif g == 1 and p == 0:
            fn += 1; errors.append(cid)
        else: tn += 1
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return {"n_scored": tp + fp + fn + tn, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": round(prec, 4), "recall": round(rec, 4), "f1": round(f1, 4),
            "fp_ids": errors if False else None}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", required=True, help="valid.parquet or CSV with id,label")
    ap.add_argument("--systems", nargs="+", required=True, help="name=path/to/records.jsonl[|path2...]")
    ap.add_argument("--ensembles", nargs="*", default=[], help="name=OR:sys1+sys2 | AND:... | MAJ:...")
    ap.add_argument("--per-case-out", help="optional CSV path with per-case predictions")
    args = ap.parse_args()

    gold = {}
    if args.gold.endswith(".parquet"):
        import pandas as pd
        df = pd.read_parquet(args.gold)[["id", "label"]]
        gold = dict(zip(df.id, df.label.astype(int)))
    else:
        import csv
        csv.field_size_limit(min(2 ** 31 - 1, 2 ** 30))
        for row in csv.DictReader(open(args.gold, encoding="utf-8")):
            gold[row["id"]] = int(row["label"])

    systems = {}
    for spec in args.systems:
        name, paths = spec.split("=", 1)
        merged = {}
        for path in paths.split("|"):
            merged.update(load_predictions(path))
        systems[name] = merged

    results = {}
    for name, preds in systems.items():
        results[name] = confusion(gold, preds)

    for spec in args.ensembles:
        name, expr = spec.split("=", 1)
        mode, combo = expr.split(":", 1)
        parts = [systems[s] for s in combo.split("+")]
        ens = {}
        for cid in gold:
            votes = [p.get(cid, 0) for p in parts]
            if mode == "OR":
                ens[cid] = 1 if any(votes) else 0
            elif mode == "AND":
                ens[cid] = 1 if all(votes) else 0
            elif mode == "MAJ":
                ens[cid] = 1 if sum(votes) * 2 > len(votes) else 0
        results[f"ens:{name}"] = confusion(gold, ens)

    print(json.dumps(results, indent=1))

    if args.per_case_out:
        import csv
        with open(args.per_case_out, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["id", "gold"] + list(systems.keys()))
            for cid, g in gold.items():
                w.writerow([cid, g] + [systems[s].get(cid, "") for s in systems])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
