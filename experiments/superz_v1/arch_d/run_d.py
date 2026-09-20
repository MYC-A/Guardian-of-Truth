"""Architecture D runner — hypothesis-scoped formal verification.

Input: B1 suspicions (atomic, with quotes).
Per suspicion: LLM formalization to typed template -> local resolution +
Clingo cross-check. Verdicts: CONFIRMED / REFUTED_* / UNRESOLVED_*.

Case-level aggregation (fixed rule): label=1 iff any hypothesis CONFIRMED.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.trace_parser import parse_trace
from common.zai_client import chat
from arch_d.hypothesis_check import check_hypothesis, formalize_suspicion

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent / "results" / "arch_d"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(HERE.parent / "data" / "synth_pairs" / "synth_pairs_v1.jsonl"))
    ap.add_argument("--labels", default=str(HERE.parent / "data" / "synth_pairs" / "labels_local.json"))
    ap.add_argument("--b1-dir", default=str(HERE.parent / "results" / "arch_b" / "B1"))
    ap.add_argument("--max-hyps", type=int, default=3, help="max suspicions per case to formalize")
    ap.add_argument("--max-seconds", type=float, default=480)
    args = ap.parse_args()

    import time

    rows = {json.loads(l)["id"]: json.loads(l) for l in open(args.data, encoding="utf-8")}
    labels = json.loads(open(args.labels, encoding="utf-8").read())
    out_dir = RESULTS / Path(args.data).parent.name
    out_dir.mkdir(parents=True, exist_ok=True)

    # collect tasks: (case_id, suspicion_idx, suspicion)
    tasks = []
    for f in sorted(Path(args.b1_dir).glob("*.json")):
        rec = json.loads(f.read_text())
        if not rec.get("ok") or rec["id"] not in rows:
            continue
        for i, s in enumerate(rec.get("suspicions", [])[: args.max_hyps]):
            out_f = out_dir / f"{rec['id'].replace(':', '__')}__h{i}.json"
            if not out_f.exists():
                tasks.append((rec["id"], i, s, out_f))
    print(f"[D] {len(tasks)} hypotheses to formalize", flush=True)

    t0 = time.time()
    done = ok = 0
    for cid, i, s, out_f in tasks:
        if time.time() - t0 > args.max_seconds:
            print("[D] time budget reached", flush=True)
            break
        row = rows[cid]
        trace = parse_trace(row["prompt"], row["response"])
        hyp = formalize_suspicion(s, row, trace)
        out = {"id": cid, "hyp_idx": i, "suspicion": s}
        if hyp is None:
            out["status"] = "FORMALIZE_FAILED"
        else:
            res = check_hypothesis(hyp, trace)
            out.update(res)
        out_f.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        done += 1
        ok += out.get("status") is not None or "verdict" in out
        v = out.get("verdict", out.get("status"))
        print(f"  [{done}/{len(tasks)}] {cid} h{i}: {v}", flush=True)

    # aggregate per-case verdicts
    per_case = {}
    for f in sorted(out_dir.glob("*__h*.json")):
        r = json.loads(f.read_text())
        per_case.setdefault(r["id"], []).append(r.get("verdict", r.get("status", "MISSING")))
    tp = fp = fn = tn = 0
    mism = []
    for cid, verdicts in per_case.items():
        pred = 1 if any(v == "CONFIRMED" for v in verdicts) else 0
        gold = labels.get(cid)
        if gold is None:
            continue
        tp += pred == 1 and gold == 1
        fp += pred == 1 and gold == 0
        fn += pred == 0 and gold == 1
        tn += pred == 0 and gold == 0
        if pred != gold:
            mism.append((cid, pred, gold, verdicts))
    prec = tp / (tp + fp) if tp + fp else 0
    rec_ = tp / (tp + fn) if tp + fn else 0
    f1 = 2 * prec * rec_ / (prec + rec_) if prec + rec_ else 0
    met = {
        "n_cases_with_hyps": len(per_case),
        "TP": tp, "FP": fp, "FN": fn, "TN": tn,
        "P": round(prec, 4), "R": round(rec_, 4), "F1": round(f1, 4),
        "mismatches": mism,
    }
    (out_dir / "metrics.json").write_text(json.dumps(met, ensure_ascii=False, indent=1))
    print(json.dumps(met, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
