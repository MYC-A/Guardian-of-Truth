"""C end-to-end orchestrator — variant comparison on ONE dataset with the
SAME formal engine (arch_d machinery: typed templates + local resolver +
Clingo cross-check) and the SAME hypothesis generator/formalizer providers.

Variants (only the THEORY differs):
  C0  theory A alone (GLM persona, no criticism)
  C1  independent union A+B (no criticism)
  C2  repaired theory after REAL mutual criticism (both sides; conservative
      rule: drop only when both sides concede invention)
  C2m diagnostic aggressive config: one-sided criticism also drops
  C3  C2 + consequence-check flags (strict aggregation downgrades CONFIRMED
      verdicts that rest on unreliable formalizations)

Outputs per variant: per-case predictions, metrics (TP/FP/FN/TN/P/R/F1),
and TRANSITIONS vs the previous variant in the ordered list
(corrected_FP / lost_TP / new_FP / gained_TP) so the cost of each mechanism
is visible, not just the final F1.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.trace_parser import parse_trace
from common.zai_client import PROVIDER_MISTRAL, PROVIDER_ZAI
from arch_c.theory_case import load_variant_theory, load_consequence_flags, check_case

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent / "results"
OUT = RESULTS / "arch_c_e2e"
DATA = HERE.parent / "data" / "synth_pairs" / "synth_pairs_v1.jsonl"
LABELS = HERE.parent / "data" / "synth_pairs" / "labels_local.json"

VARIANT_ORDER = ["C0", "C1", "C2", "C2m", "C3"]


def case_policy_hash(row: dict) -> str:
    t = parse_trace(row["prompt"], row["response"])
    return hashlib.sha256(t.policy_text.encode()).hexdigest()[:10]


def metrics_from_preds(preds: dict[str, int], labels: dict) -> dict:
    tp = fp = fn = tn = 0
    mism = []
    for cid, pred in preds.items():
        gold = labels.get(cid)
        if gold is None:
            continue
        if pred == 1 and gold == 1:
            tp += 1
        elif pred == 1 and gold == 0:
            fp += 1
            mism.append((cid, pred, gold))
        elif pred == 0 and gold == 1:
            fn += 1
            mism.append((cid, pred, gold))
        else:
            tn += 1
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return {"n": len(preds), "TP": tp, "FP": fp, "FN": fn, "TN": tn,
            "P": round(prec, 4), "R": round(rec, 4), "F1": round(f1, 4),
            "mismatches": mism}


def transitions(prev: dict[str, int], curr: dict[str, int], labels: dict) -> dict:
    """Per-case label changes between consecutive variants, split by gold:
    corrected_FP (was FP, now negative), lost_TP (was TP, now negative),
    new_FP (was TN, now positive), gained_TP (was FN, now positive)."""
    out = {"corrected_FP": 0, "lost_TP": 0, "new_FP": 0, "gained_TP": 0,
           "flips": []}
    for cid in curr:
        if cid not in prev:
            continue
        p, c = prev[cid], curr[cid]
        gold = labels.get(cid)
        if p == 1 and c == 0:
            kind = "lost_TP" if gold == 1 else "corrected_FP"
            out[kind] += 1
            out["flips"].append({"id": cid, "flip": "1->0", "kind": kind})
        elif p == 0 and c == 1:
            kind = "gained_TP" if gold == 1 else "new_FP"
            out[kind] += 1
            out["flips"].append({"id": cid, "flip": "0->1", "kind": kind})
    return out


def run_variant(variant: str, rows: dict, labels: dict, provider: str,
                max_seconds: float, max_hyps: int) -> dict:
    out_dir = OUT / variant
    out_dir.mkdir(parents=True, exist_ok=True)
    conseq_flags = {h: load_consequence_flags(h) for h in
                    {case_policy_hash(r) for r in rows.values()}}
    t0 = time.time()
    preds = {}
    per_case = {}
    for i, (cid, row) in enumerate(sorted(rows.items())):
        if time.time() - t0 > max_seconds:
            print(f"[{variant}] time budget reached at case {i}", flush=True)
            break
        ph = case_policy_hash(row)
        elements = load_variant_theory(ph, variant)
        trace = parse_trace(row["prompt"], row["response"])
        res = check_case(cid, variant, elements, row, trace, provider=provider,
                         max_hyps=max_hyps, out_dir=out_dir,
                         conseq_flags=conseq_flags.get(ph) if variant == "C3" else None)
        label = res["label_strict"] if variant == "C3" else res["label_lenient"]
        preds[cid] = label
        per_case[cid] = {k: v for k, v in res.items() if k != "results"}
        print(f"  [{variant} {i+1}/{len(rows)}] {cid[:44]}: label={label} "
              f"hyps={res['n_hypotheses']} verdicts={res['verdicts'][:3]}", flush=True)
    met = metrics_from_preds(preds, labels)
    summary = {
        "variant": variant,
        "provider_gen_formal": provider,
        "metrics": {k: v for k, v in met.items() if k != "mismatches"},
        "mismatches": met["mismatches"],
        "n_cases_run": len(preds),
    }
    (out_dir / "metrics.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    (out_dir / "per_case.json").write_text(json.dumps(per_case, ensure_ascii=False, indent=1))
    print(f"[{variant}] " + json.dumps(summary["metrics"], ensure_ascii=False), flush=True)
    return preds


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", default="C0,C1",
                    help="comma-separated from C0,C1,C2,C2m,C3")
    ap.add_argument("--provider", default=PROVIDER_MISTRAL,
                    choices=[PROVIDER_MISTRAL, PROVIDER_ZAI])
    ap.add_argument("--max-seconds", type=float, default=900)
    ap.add_argument("--max-hyps", type=int, default=4)
    args = ap.parse_args()

    rows = {}
    for line in DATA.open(encoding="utf-8"):
        r = json.loads(line)
        rows[r["id"]] = r
    labels = {k: int(v) for k, v in json.loads(LABELS.read_text()).items()}

    variants = [v.strip() for v in args.variants.split(",")]
    all_preds: dict[str, dict[str, int]] = {}
    # load any previous variant preds saved earlier (for transitions)
    for v in VARIANT_ORDER:
        f = OUT / v / "metrics.json"
        if f.exists() and v not in variants:
            pc = json.loads((OUT / v / "per_case.json").read_text())
            all_preds[v] = {cid: (c["label_strict"] if v == "C3" else c["label_lenient"])
                            for cid, c in pc.items()}
    for v in variants:
        preds = run_variant(v, rows, labels, args.provider,
                            args.max_seconds, args.max_hyps)
        all_preds[v] = preds

    # transitions along the canonical order for the variants we have
    trans = {}
    ordered = [v for v in VARIANT_ORDER if v in all_preds]
    for a, b in zip(ordered, ordered[1:]):
        if b in variants or a in variants:
            trans[f"{a}->{b}"] = transitions(all_preds[a], all_preds[b], labels)
    (OUT / "comparison.json").write_text(json.dumps(
        {"variants": {v: (json.loads((OUT / v / "metrics.json").read_text())["metrics"]
                          if (OUT / v / "metrics.json").exists() else None)
                      for v in ordered},
         "transitions": trans},
        ensure_ascii=False, indent=1))
    print(json.dumps(trans, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
