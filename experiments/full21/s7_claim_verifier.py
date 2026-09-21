#!/usr/bin/env python3
"""FULL_21 Sections 3.6 + 5 (verifier side): Granite as per-suspicion claim verifier.

Uses the ARCHIVED E3b suspicions (65 statements with proposed_violation text,
frozen in full_21/archive-previous; producer was blockrun — preserved previous
work, NOT a new external call). The new model runs here are 100% local Granite.

Variants (identical suspicions, identical aggregation):
  plain    : documents = [bounded case context @4800], the suspicion statement
             is the judged text (groundedness). risk=yes -> suspicion CONFIRMED.
  graph    : documents = [bounded case context + mechanical graph digest]
             (tests whether the graph helps the VERIFIER, not the judge).
Aggregation: case label = 1 iff >=1 suspicion confirmed (a4g contract).
Baselines joined post-hoc: E3b producer labels, A4 blockrun verifier (archived),
control granite @12k.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "experiments" / "superz_fullcycle"))
sys.path.insert(0, str(REPO / "experiments" / "full21"))
sys.path.insert(0, str(REPO / "src"))

from g_graph import graph_digest  # noqa: E402
from run_granite_modes import (  # noqa: E402
    GraniteLocalRunner, read_cases, bounded_text, parse_score, sha256_file,
)

E3B = REPO.parent / "Guardian-superz-fullcycle" / "outputs" / "superz_fullcycle" / "e3b_a1r_live" / "blockrun" / "records.jsonl"
GOLD_BASE = Path("/mnt/data/guardian/agent-workspace/flash-repo/outputs/ifc/percase_v1.csv")

CTX_BUDGET = 4800
RESP_BUDGET = 7200


def load_gold():
    gold, base = {}, {}
    for row in csv.DictReader(open(GOLD_BASE)):
        gold[row["id"]] = int(row["gold"])
        base[row["id"]] = int(row["baseline"])
    return gold, base


def load_suspicions():
    recs = [json.loads(l) for l in open(E3B, encoding="utf-8")]
    items = []
    for r in recs:
        if r.get("status") != "OK":
            continue
        for i, s in enumerate(r.get("suspicions", [])):
            pv = (s.get("proposed_violation") or "").strip()
            if not pv:
                continue
            items.append({
                "case_id": r["id"],
                "susp_idx": i,
                "statement": pv,
                "producer_label": s.get("label"),
                "score": s.get("score"),
                "reason_type": s.get("reason_type"),
                "anchored": bool(s.get("anchored_doc")),
            })
    return items


def run_variant(runner, cases_map, susp, kind, input_path):
    out_dir = Path(f"outputs/research_granite_guardian/full21_s7_{kind}")
    if out_dir.exists() and any(out_dir.iterdir()):
        raise SystemExit(f"refusing to overwrite {out_dir}")
    out_dir.mkdir(parents=True)
    run_config = {
        "runner": "full21/s7_claim_verifier",
        "model_id": "ibm-granite/granite-guardian-3.3-8b",
        "model_path": "/mnt/data/guardian/models/granite-guardian-3.3-8b-b3421eda",
        "criterion": "groundedness", "think": False, "verifier_mode": kind,
        "ctx_budget": CTX_BUDGET, "resp_budget": RESP_BUDGET,
        "input_sha256": sha256_file(input_path),
        "n_suspicions": len(susp),
        "started_at_utc": datetime.now(UTC).isoformat(),
        "suspicion_source": "archive E3b blockrun records (frozen, no new external calls)",
    }
    (out_dir / "run_config.json").write_text(json.dumps(run_config, indent=1))
    records = []
    counts = {}
    for item in susp:
        case = cases_map.get(item["case_id"])
        if case is None:
            records.append({**item, "status": "missing_case"})
            counts["missing_case"] = counts.get("missing_case", 0) + 1
            continue
        t0 = time.perf_counter()
        ctx_b = bounded_text(case["prompt"], CTX_BUDGET, "prompt")
        if kind == "plain":
            documents = [{"doc_id": "case_context", "text": ctx_b.text}]
        elif kind == "graph":
            try:
                digest = graph_digest(case["prompt"], case["response"])
            except Exception as e:
                digest = f"(digest error: {type(e).__name__})"
            documents = [
                {"doc_id": "case_context", "text": ctx_b.text},
                {"doc_id": "graph_digest", "text": digest[:2600]},
            ]
        else:
            raise ValueError(kind)
        statement_b = bounded_text(item["statement"], RESP_BUDGET, "suspicion")
        messages = [{"role": "assistant", "content": statement_b.text}]
        chat = runner.tokenizer.apply_chat_template(
            messages, guardian_config={"criteria_id": "groundedness"},
            documents=documents, think=False, tokenize=False, add_generation_prompt=True)
        gen = runner.generate(chat, 16)
        risk = parse_score(gen["text"])
        status = "ok" if risk is not None else "no_score_token"
        rec = {
            **item,
            "status": status,
            "risk_token": risk,
            "verifier_verdict": ("CONFIRMED" if risk == "yes" else
                                 ("REFUTED" if risk == "no" else None)),
            "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
            "raw_model_output": gen["text"],
            "formal_proof_status": "UNRESOLVED",
        }
        records.append(rec)
        counts[status] = counts.get(status, 0) + 1
    with (out_dir / "records.jsonl").open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    summary = {"output_dir": str(out_dir), "records": len(records),
               "status_counts": counts,
               "finished_at_utc": datetime.now(UTC).isoformat()}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1))
    return summary, records


def aggregate(records, gold, base):
    """Case label = 1 iff >=1 suspicion CONFIRMED; missing verdicts never coerce."""
    case_confirmed = {}
    case_any = {}
    for r in records:
        cid = r["case_id"]
        case_any.setdefault(cid, 0)
        case_any[cid] += 1
        if r.get("verifier_verdict") == "CONFIRMED":
            case_confirmed[cid] = 1
        else:
            case_confirmed.setdefault(cid, 0)
    tp = fp = fn = tn = 0
    covered = 0
    for cid, g in gold.items():
        if cid not in case_any:
            continue
        covered += 1
        p = case_confirmed.get(cid, 0)
        if g == 1 and p == 1: tp += 1
        elif g == 0 and p == 1: fp += 1
        elif g == 1 and p == 0: fn += 1
        else: tn += 1
    prec = tp / (tp + fp) if tp + fp else 0
    rec = tp / (tp + fn) if tp + fn else 0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "covered": covered,
            "precision": round(prec, 4), "recall": round(rec, 4), "f1": round(f1, 4)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--model-path", required=True)
    ap.add_argument("--kinds", nargs="+", default=["plain", "graph"])
    args = ap.parse_args()
    cases = read_cases(Path(args.input))
    cases_map = {c["id"]: c for c in cases}
    susp = load_suspicions()
    print(f"suspicions loaded: {len(susp)} across {len({s['case_id'] for s in susp})} cases", flush=True)
    gold, base = load_gold()
    runner = GraniteLocalRunner(Path(args.model_path))
    results = {}
    for kind in args.kinds:
        print(f"[s7 {kind}] start", flush=True)
        summary, records = run_variant(runner, cases_map, susp, kind, Path(args.input))
        m = aggregate(records, gold, base)
        # per-suspicion agreement with producer labels
        agree = sum(1 for r in records
                    if r.get("verifier_verdict") is not None
                    and r.get("producer_label") is not None
                    and (1 if r["verifier_verdict"] == "CONFIRMED" else 0) == int(r["producer_label"]))
        n_pair = sum(1 for r in records
                     if r.get("verifier_verdict") is not None and r.get("producer_label") is not None)
        results[kind] = {"summary": summary, "case_metrics": m,
                         "susp_agreement_with_producer": f"{agree}/{n_pair}"}
        print(f"[s7 {kind}] -> {json.dumps(results[kind], ensure_ascii=False)}", flush=True)
    (Path("outputs/full21") / "s7_metrics.json").write_text(json.dumps(results, indent=1))
    print(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
