"""Rerun S7 with the correct groundedness polarity and explicit abstention."""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

from experiments.recheck_2026.shared import (
    DEFAULT_CASES, DEFAULT_GOLD, REPO, bounded, cases, digest, jsonl,
    labels, prepare_run, score, write_json, write_jsonl,
)

DEFAULT_SUSPICIONS = REPO / "outputs/research_granite_guardian/full21_s7_plain/records.jsonl"
VIOLATION_CRITERION = (
    "The assistant statement identifies a real contextual error in the target "
    "response. Return yes only if the supplied policy and conversation evidence "
    "support this exact alleged error for the same action, entity and time, "
    "and no supplied exception or contrary observation defeats it. Return no "
    "if the evidence is missing, ambiguous, or supports only a different error."
)


def support_status(risk: str | None, mode: str = "groundedness") -> str:
    # IBM groundedness risk=yes means the candidate statement is not grounded.
    # The score does not itself prove that the proposed policy violation occurred.
    if mode == "custom_violation":
        return {"yes": "VIOLATION_SUPPORTED_PROBABILISTIC",
                "no": "NOT_VIOLATION_SUPPORTED_PROBABILISTIC"}.get(risk, "UNKNOWN")
    return {"no": "SOURCE_SUPPORTED_PROBABILISTIC",
            "yes": "NOT_SOURCE_SUPPORTED_PROBABILISTIC"}.get(risk, "UNKNOWN")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    ap.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    ap.add_argument("--suspicions", type=Path, default=DEFAULT_SUSPICIONS)
    ap.add_argument("--model-path", type=Path)
    ap.add_argument("--mode", choices=["groundedness", "custom_violation"],
                    default="groundedness")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--context-chars", type=int, default=12000)
    ap.add_argument("--limit-cases", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()
    case_map = cases(args.cases)
    susp = [r for r in jsonl(args.suspicions)
            if r.get("case_id") in case_map and r.get("statement")]
    ids = sorted({r["case_id"] for r in susp})
    if args.limit_cases:
        ids = ids[:args.limit_cases]
    susp = [r for r in susp if r["case_id"] in ids]
    output = args.out
    config = {"experiment": "s7_hypothesis_verifier_v2", "mode": args.mode,
        "case_sha256": digest(args.cases), "suspicion_sha256": digest(args.suspicions),
        "gold_sha256": digest(args.gold), "model_path": str(args.model_path),
        "model_config_sha256": (digest(args.model_path / "config.json")
                                if args.model_path and (args.model_path / "config.json").exists()
                                else None),
        "context_chars": args.context_chars, "ids": ids, "dry_run": args.dry_run,
        "custom_criterion": VIOLATION_CRITERION if args.mode == "custom_violation" else None,
        "decision_semantics": "probabilistic hypothesis score only; no formal proof"}
    rows = prepare_run(output, config, args.resume)
    by_key = {(r["case_id"], r["susp_idx"]): r for r in rows}
    runner = None
    parse_score = None
    if not args.dry_run:
        if not args.model_path or not args.model_path.is_dir():
            raise ValueError("--model-path must name an existing local model directory")
        sys.path.insert(0, str(REPO / "experiments/full21"))
        from run_granite_modes import GraniteLocalRunner, parse_score as parser
        runner = GraniteLocalRunner(args.model_path)
        parse_score = parser
    gold = labels(args.gold)
    for item in susp:
        key = (item["case_id"], item["susp_idx"])
        old = by_key.get(key)
        if old and (args.dry_run or old.get("new_risk") in {"yes", "no"}):
            continue
        case = case_map[item["case_id"]]
        context = bounded(case["prompt"], args.context_chars, "head_tail")
        target = bounded(case["response"], 3000, "head_tail")
        record = {"case_id": item["case_id"], "susp_idx": item["susp_idx"],
                  "statement": item["statement"], "gold": gold.get(item["case_id"]),
                  "old_risk": item.get("risk_token"),
                  "old_status_reinterpreted": support_status(item.get("risk_token")),
                  "context": {k: v for k, v in context.items() if k != "text"},
                  "target_response": {k: v for k, v in target.items() if k != "text"},
                  "new_risk": None, "support_status": "UNKNOWN",
                  "formal_proof_status": "UNRESOLVED"}
        if runner:
            try:
                guardian_config = ({"criteria_id": "groundedness"}
                                   if args.mode == "groundedness" else
                                   {"custom_criteria": VIOLATION_CRITERION})
                chat = runner.tokenizer.apply_chat_template(
                    [{"role": "assistant", "content": item["statement"]}],
                    guardian_config=guardian_config,
                    documents=[{"doc_id": "case_context", "text": context["text"]},
                               {"doc_id": "target_response", "text": target["text"]}],
                    think=False, tokenize=False, add_generation_prompt=True)
                generated = runner.generate(chat, 32)
                record["new_risk"] = parse_score(generated["text"])
                record["support_status"] = support_status(record["new_risk"], args.mode)
                record["raw_model_output"] = generated["text"]
                record["input_token_count"] = generated.get("input_token_count")
            except Exception as exc:
                record["error"] = f"{type(exc).__name__}: {exc}"
        by_key[key] = record
        rows = [by_key[(r["case_id"], r["susp_idx"])] for r in susp
                if (r["case_id"], r["susp_idx"]) in by_key]
        write_jsonl(output / "records.jsonl", rows)
    rows = [by_key[(r["case_id"], r["susp_idx"])] for r in susp
            if (r["case_id"], r["susp_idx"]) in by_key]
    by_case = defaultdict(list)
    for row in rows:
        by_case[row["case_id"]].append(row)
    case_rows = []
    for cid, items in by_case.items():
        positive = ("SOURCE_SUPPORTED_PROBABILISTIC" if args.mode == "groundedness"
                    else "VIOLATION_SUPPORTED_PROBABILISTIC")
        case_rows.append({"id": cid, "gold": gold.get(cid),
            "old_any_supported": int(any(r["old_status_reinterpreted"] ==
                "SOURCE_SUPPORTED_PROBABILISTIC" for r in items)),
            "new_any_supported": (int(any(r["support_status"] ==
                positive for r in items)) if runner else None),
            "n_suspicions": len(items)})
    write_jsonl(output / "percase.jsonl", case_rows)
    write_json(output / "summary.json", {
        "note": "binary columns are diagnostic probabilistic aggregations, not proof",
        "mode": args.mode,
        "old_reinterpreted": score(case_rows, "old_any_supported"),
        "new": score(case_rows, "new_any_supported"),
        "n_suspicions": len(rows), "n_cases": len(case_rows)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
