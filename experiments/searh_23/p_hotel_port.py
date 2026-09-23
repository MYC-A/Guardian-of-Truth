#!/usr/bin/env python3
"""SEARCH_23 out-of-sample port: pgjudge (cards + graph digest) on the hotel v2 contrast suite.

Reuses the public46 P-pipeline (experiments/big_researh/p_precond_api.py) unchanged —
only OUT_ROOT is repointed, inputs are the hotel suite. This is the recorded next step
after the in-sample v3 result (F1 .9020 on public46): does pgjudge transfer to a NEW
domain (hotel rules, hotel tools, hotel event format), and what does the v3 refutation
layer do there (run separately via fp_refute_layer_v3.py CLI).

Stages (resumable, append-only journals):
  1. extract : up to 3 grounded policy cards per case (Mistral API)
  2. pgjudge : cards + mechanical graph digest (Mistral API)
  3. metrics : base pgjudge vs expected.json (all 28 + semantic-20 subset)

Output namespace: outputs/searh_23/hotel_p/
"""
import csv
import json
import sys
import traceback
from pathlib import Path

REPO = Path("/mnt/data/guardian/agent-workspace/Guardian-searh23")
sys.path.insert(0, str(REPO / "experiments" / "big_researh"))
sys.stderr = sys.stdout  # gateway captures stdout only

import p_precond_api as pp  # noqa: E402

HOTEL = REPO / "outputs/searh_23/contrast_hotel_v2"
OUT_ROOT = REPO / "outputs/searh_23/hotel_p"
pp.OUT_ROOT = OUT_ROOT


def subset_metrics(rows, expected, pred):
    tp = sum(1 for i in rows if pred.get(i) == 1 and expected[i] == 1)
    fp = sum(1 for i in rows if pred.get(i) == 1 and expected[i] == 0)
    fn = sum(1 for i in rows if pred.get(i) == 0 and expected[i] == 1)
    tn = sum(1 for i in rows if pred.get(i) == 0 and expected[i] == 0)
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * r / (p + r) if p and r else 0.0
    return {"n": len(rows), "TP": tp, "FP": fp, "FN": fn, "TN": tn,
            "P": round(p, 4), "R": round(r, 4), "F1": round(f1, 4)}


def main() -> int:
    csv.field_size_limit(2 ** 30)
    cases = list(csv.DictReader(open(HOTEL / "cases.csv", encoding="utf-8")))
    expected = {k: int(v) for k, v in json.load(open(HOTEL / "expected.json", encoding="utf-8")).items()}
    print(f"[hotel_p] {len(cases)} cases, expected pos={sum(expected.values())}", flush=True)

    # stage 1: cards
    pp.run_extract(cases)

    # stage 2: pgjudge (cards + graph)
    pp.run_judge(cases, "pgjudge")

    # stage 3: metrics
    pred, failed = {}, []
    for line in open(OUT_ROOT / "pgjudge" / "records.jsonl", encoding="utf-8"):
        rec = json.loads(line)
        if rec.get("status") == "OK":
            pred[rec["id"]] = int(rec.get("label", 0))
        else:
            failed.append(rec["id"])
    all_ids = sorted(expected)
    semantic = [i for i in all_ids if int(i.split("pair")[1][:2]) <= 10]
    controls = [i for i in all_ids if int(i.split("pair")[1][:2]) > 10]
    res = {
        "domain": "hotel_v2 (out-of-sample)",
        "failed_records": failed,
        "pgjudge_base": {
            "all28": subset_metrics(all_ids, expected, pred),
            "semantic20": subset_metrics(semantic, expected, pred),
            "controls8": subset_metrics(controls, expected, pred),
        },
    }
    (OUT_ROOT / "metrics.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1), flush=True)
    print("\nper-case (id | expected | pgjudge | violated_cards):", flush=True)
    for line in open(OUT_ROOT / "pgjudge" / "records.jsonl", encoding="utf-8"):
        rec = json.loads(line)
        print(f"{rec['id']:30s} exp={expected.get(rec['id'])} pj={rec.get('label')} "
              f"cards={rec.get('violated_cards')} conf={rec.get('confidence')}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc(file=sys.stdout)
        sys.exit(1)
