#!/usr/bin/env python3
"""SEARCH_23 §7.3 contrast evaluation: granite groundedness vs expected labels on hotel minimal pairs.

A pair is DETECTED iff pred(violating)=1 and pred(compliant)=0 (the model's label
flips exactly with the constructed contrast). Expected labels are by construction,
independent of the model.
Output: outputs/searh_23/contrast_hotel/{eval.json, eval_report.md}
"""
import json
import sys
import traceback
from pathlib import Path

REPO = Path("/mnt/data/guardian/agent-workspace/Guardian-searh23")
D = REPO / "outputs/searh_23/contrast_hotel"

try:
    expected = json.loads((D / "expected.json").read_text(encoding="utf-8"))
    suite = json.loads((D / "suite.json").read_text(encoding="utf-8"))
    preds, statuses = {}, {}
    for line in open(D / "granite_g12k/records.jsonl", encoding="utf-8"):
        r = json.loads(line)
        preds[r["id"]] = 1 if (r.get("risk_token") or "").lower() == "yes" else \
            (0 if (r.get("risk_token") or "").lower() == "no" else None)
        statuses[r["id"]] = r.get("status")

    tp = fp = fn = tn = ns = 0
    per_case = []
    for cid in sorted(expected):
        p, e = preds.get(cid), expected[cid]
        if p is None:
            ns += 1
        elif p == 1 and e == 1:
            tp += 1
        elif p == 1 and e == 0:
            fp += 1
        elif p == 0 and e == 1:
            fn += 1
        else:
            tn += 1
        per_case.append({"id": cid, "pred": p, "expected": e, "status": statuses.get(cid)})

    pairs = []
    for pidx in range(1, suite["n_pairs"] + 1):
        vid, oid = f"hotel__pair{pidx:02d}::viol", f"hotel__pair{pidx:02d}::ok"
        pv, po = preds.get(vid), preds.get(oid)
        detected = (pv == 1 and po == 0)
        pairs.append({"pidx": pidx, "flip_kind": suite["flip_kinds"][pidx - 1],
                      "pred_viol": pv, "pred_ok": po, "detected": detected})

    n_det = sum(1 for p in pairs if p["detected"])
    prec = tp / (tp + fp) if tp + fp else None
    rec = tp / (tp + fn) if tp + fn else None
    f1 = 2 * prec * rec / (prec + rec) if prec and rec else None
    ev = {"suite": suite["domain"], "n_cases": len(expected),
          "channel": "granite 3.3 groundedness doc-mode 12k greedy no-think (frozen C1 granite channel)",
          "metrics": {"TP": tp, "FP": fp, "FN": fn, "TN": tn, "no_score": ns,
                      "P": round(prec, 4) if prec else None,
                      "R": round(rec, 4) if rec else None,
                      "F1": round(f1, 4) if f1 else None},
          "pairs_detected": n_det, "pairs_total": suite["n_pairs"],
          "pairs": pairs, "per_case": per_case,
          "interpretation_limit": "contrast suite is synthetic and small; it probes "
                                  "flip sensitivity, not general accuracy; open external "
                                  "benchmarks remain unintegrated (recorded honestly)"}
    (D / "eval.json").write_text(json.dumps(ev, ensure_ascii=False, indent=1), encoding="utf-8")

    lines = ["# §7.3 contrast evaluation (hotel minimal pairs)",
             "",
             f"Channel: granite 3.3 groundedness (frozen). "
             f"Metrics: TP{tp}/FP{fp}/FN{fn}/TN{tn}"
             + (f"/no_score{ns}" if ns else "")
             + f" F1={ev['metrics']['F1']}",
             f"Pairs detected (pred flips with the contrast): {n_det}/{suite['n_pairs']}",
             "",
             "| pair | flip kind | pred(viol) | pred(ok) | detected |",
             "|---|---|---|---|---|"]
    for p in pairs:
        lines.append(f"| {p['pidx']} | {p['flip_kind']} | {p['pred_viol']} | "
                     f"{p['pred_ok']} | {'YES' if p['detected'] else 'no'} |")
    (D / "eval_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"metrics": ev["metrics"], "pairs_detected": f"{n_det}/{suite['n_pairs']}"},
                     ensure_ascii=False, indent=1))
except Exception:
    traceback.print_exc(file=sys.stdout)
    sys.exit(1)
