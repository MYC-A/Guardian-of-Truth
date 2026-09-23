#!/usr/bin/env python3
"""C1 full contrast eval: add structural channel on hotel pairs, compute OR metrics + pair flips."""
import csv
import json
import sys
import traceback
from pathlib import Path

REPO = Path("/mnt/data/guardian/agent-workspace/Guardian-searh23")
sys.path.insert(0, str(REPO / "src"))
D = REPO / "outputs/searh_23/contrast_hotel"

try:
    from guardian_truth.pipeline import Detector
    from guardian_truth.decision import decide

    csv.field_size_limit(2 ** 30)
    cases = {r["id"]: r for r in csv.DictReader(open(D / "cases.csv", encoding="utf-8-sig", newline=""))}
    expected = json.loads((D / "expected.json").read_text(encoding="utf-8"))
    granite = {}
    for line in open(D / "granite_g12k/records.jsonl", encoding="utf-8"):
        r = json.loads(line)
        granite[r["id"]] = 1 if (r.get("risk_token") or "").lower() == "yes" else 0

    det = Detector()
    tp = fp = fn = tn = 0
    per_case = []
    for cid in sorted(cases):
        c = cases[cid]
        rev = det.review(c["prompt"], c["response"])
        d = decide(rev, threshold=0.5, use_semantic=False, unknown_label=0)
        s = int(d.label)
        g = granite.get(cid)
        label = int(s == 1 or g == 1)
        e = expected[cid]
        if label == 1 and e == 1:
            tp += 1
        elif label == 1 and e == 0:
            fp += 1
        elif label == 0 and e == 1:
            fn += 1
        else:
            tn += 1
        per_case.append({"id": cid, "structural": s, "granite": g, "or_label": label,
                         "expected": e, "struct_status": rev.status,
                         "n_findings": len(rev.findings)})

    pairs = []
    for pidx in range(1, 11):
        vid, oid = f"hotel__pair{pidx:02d}::viol", f"hotel__pair{pidx:02d}::ok"
        pv = next((c["or_label"] for c in per_case if c["id"] == vid), None)
        po = next((c["or_label"] for c in per_case if c["id"] == oid), None)
        sv = next((c["structural"] for c in per_case if c["id"] == vid), None)
        so = next((c["structural"] for c in per_case if c["id"] == oid), None)
        pairs.append({"pidx": pidx, "or_viol": pv, "or_ok": po,
                      "struct_viol": sv, "struct_ok": so,
                      "detected": pv == 1 and po == 0})
    n_det = sum(1 for p in pairs if p["detected"])
    prec = tp / (tp + fp) if tp + fp else 0
    rec = tp / (tp + fn) if tp + fn else 0

    out = {"channel": "C1 frozen = OR(structural Guardian, granite 3.3 groundedness)",
           "metrics": {"TP": tp, "FP": fp, "FN": fn, "TN": tn,
                       "P": round(prec, 4), "R": round(rec, 4),
                       "F1": round(2 * prec * rec / (prec + rec), 4) if prec + rec else 0},
           "pairs_detected": n_det, "pairs_total": 10, "pairs": pairs,
           "per_case": per_case,
           "granite_only": {"metrics": {"TP": 10, "FP": 8, "FN": 0, "TN": 2, "F1": 0.7143},
                            "pairs_detected": 2}}
    (D / "eval_c1.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"metrics": out["metrics"], "pairs_detected": f"{n_det}/10"}, indent=1))
    for p in pairs:
        print(f"  p{p['pidx']:02d} OR viol={p['or_viol']} ok={p['or_ok']} "
              f"(struct {p['struct_viol']}/{p['struct_ok']}) {'DETECTED' if p['detected'] else 'no'}")
except Exception:
    traceback.print_exc(file=sys.stdout)
    sys.exit(1)
