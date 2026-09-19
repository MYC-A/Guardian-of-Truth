"""Score frozen Granite diagnostic predictions after inference; never imports gold in runner."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    for name, expected in manifest["hashes"].items():
        if digest(ROOT / name) != expected:
            raise ValueError(f"frozen benchmark changed: {name}")
    gold = {}
    with (ROOT / "gold.csv").open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            gold[(row["id"], row["criterion"])] = row
    records = [json.loads(line) for line in args.records.read_text(encoding="utf-8").splitlines() if line.strip()]
    matched = {}
    for row in records:
        key = (row["id"], row["criterion"])
        if key not in gold:
            continue
        if key in matched:
            raise ValueError(f"duplicate record for {key}")
        matched[key] = row
    if len(matched) != len(gold):
        missing = sorted(set(gold) - set(matched))
        raise ValueError(f"missing {len(missing)} predictions, first={missing[:3]}")
    report = {"benchmark": manifest, "records_sha256": digest(args.records), "by_criterion": {}, "by_type": {}}
    groups = defaultdict(list)
    for key, truth in gold.items():
        rec = matched[key]
        y = int(truth["label"])
        pred = 1 if rec.get("risk_token") == "yes" else 0 if rec.get("risk_token") == "no" else None
        entry = (y, pred, rec.get("status"), rec.get("latency_ms"))
        groups[truth["criterion"]].append(entry)
        groups[truth["error_type"]].append(entry)
    for category, destination in (("by_criterion", {k: v for k, v in groups.items() if k in {"function_call", "groundedness"}}),
                                  ("by_type", {k: v for k, v in groups.items() if k not in {"function_call", "groundedness"}})):
        for name, rows in destination.items():
            tp = sum(y == 1 and p == 1 for y,p,_,_ in rows)
            fp = sum(y == 0 and p == 1 for y,p,_,_ in rows)
            fn = sum(y == 1 and p != 1 for y,p,_,_ in rows)
            tn = sum(y == 0 and p != 1 for y,p,_,_ in rows)
            unresolved = sum(p is None for _,p,_,_ in rows)
            report[category][name] = {"n": len(rows), "tp": tp, "fp": fp, "fn": fn, "tn": tn,
                                      "unresolved": unresolved, "f1_with_unresolved_fallback0": 2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0,
                                      "latency_ms_sum": sum(v or 0 for *_,v in rows)}
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(report["by_criterion"], ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
