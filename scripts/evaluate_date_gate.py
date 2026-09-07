"""Replay the exact date-gated-action precheck after the frozen V6 candidate."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from guardian_truth.benchmarking import Example, Score, metrics, paired_comparison
from guardian_truth.cli import read_rows, validate_rows
from guardian_truth.pipeline import Detector


TURN_CODES = {"multiple_tool_calls_in_turn", "mixed_text_and_tool_call"}
DATE_CODE = "date_gated_action_violation"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("valid.parquet"))
    parser.add_argument("--baseline-audit", type=Path,
                        default=Path("outputs/claim_gate_20b_full/audit.jsonl"))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("Use a new nonexisting output directory")
    rows = read_rows(args.input)
    validate_rows(rows)
    old = [json.loads(line) for line in
           args.baseline_audit.read_text(encoding="utf-8").splitlines()]
    if [str(row["id"]) for row in rows] != [row["id"] for row in old]:
        parser.error("Baseline and input IDs differ")
    detector = Detector()
    current_predictions, candidate_predictions, hits = [], [], []
    current_short, candidate_short = set(), set()
    for row, baseline in zip(rows, old):
        review = detector.review(row["prompt"], row["response"])
        turn = [item for item in review.findings if item.code in TURN_CODES]
        date = [item for item in review.findings if item.code == DATE_CODE]
        base = baseline["strict"]["label"]
        current = int(base == 1 or bool(turn))
        candidate = int(current == 1 or bool(date))
        current_predictions.append(current)
        candidate_predictions.append(candidate)
        if turn:
            current_short.add(baseline["id"])
        if turn or date:
            candidate_short.add(baseline["id"])
        if date:
            hits.append({
                "id": baseline["id"], "gold": baseline["label"],
                "before": current, "after": candidate,
                "codes": [item.code for item in date],
                "sources": [[{"document": source.document, "start": source.start,
                               "end": source.end} for source in item.sources]
                            for item in date],
            })
    labels = [row["label"] for row in old]
    examples = [Example(str(row["id"]), row["prompt"], row["response"], int(row["label"]),
                        source_id=str(row["id"]).split("::", 1)[0]) for row in rows]
    comparison = paired_comparison(
        examples,
        [Score(str(row["id"]), float(value)) for row, value in zip(rows, current_predictions)],
        [Score(str(row["id"]), float(value)) for row, value in zip(rows, candidate_predictions)],
        bootstrap_samples=1000, seed=0,
    )
    current_metric = metrics(labels, current_predictions)
    candidate_metric = metrics(labels, candidate_predictions)
    newly_short = [item for item in old if item["id"] in candidate_short
                   and item["id"] not in current_short
                   and not item["skipped_mechanical"]]
    current_report = json.loads(Path("outputs/v6_turn_structure_replay_v5/report.json")
                                .read_text(encoding="utf-8"))
    result = {
        "configuration": {
            "experiment": "date_gate_after_frozen_v6_turn_structure",
            "rows": len(rows), "target_code": DATE_CODE,
            "input_sha256": hashlib.sha256(args.input.read_bytes()).hexdigest(),
            "baseline_audit_sha256": hashlib.sha256(args.baseline_audit.read_bytes()).hexdigest(),
            "source_sha256": {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                              for path in (Path("src/guardian_truth/checks.py"),
                                           Path("src/guardian_truth/pipeline.py"), Path(__file__))},
            "labels_or_explanations_used_by_check": False,
        },
        "current_v6": current_metric,
        "candidate": candidate_metric,
        "delta": {name: candidate_metric[name] - current_metric[name]
                  for name in ("f1", "precision", "recall")},
        "paired_comparison": comparison,
        "hits": hits,
        "changed": [item for item in hits if item["before"] != item["after"]],
        "hit_gold_counts": dict(Counter(item["gold"] for item in hits)),
        "cost": {
            "additional_llm_calls": 0,
            "current_logical_calls": current_report["cost"]["candidate_logical_calls"],
            "candidate_logical_calls": (current_report["cost"]["candidate_logical_calls"]
                                         - len(newly_short)),
            "current_reported_tokens": current_report["cost"]["candidate_reported_tokens"],
            "candidate_reported_tokens": (current_report["cost"]["candidate_reported_tokens"]
                - sum(item["review"].get("semantic_usage", {}).get("total_tokens", 0)
                      for item in newly_short)),
        },
        "fallback": {
            "current": current_report["fallback"]["candidate"],
            "candidate": sum(item["strict"]["used_fallback"]
                             and item["id"] not in candidate_short for item in old),
        },
        "limitations": [
            "The 46 inspected rows are development data, not independent validation.",
            "Only one real row activates this narrow policy template, so the numerical gain has no empirical cross-case support.",
            "The date check is exact after policy/action/entity binding; phrase coverage remains intentionally narrow.",
        ],
    }
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / "report.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in
                      ("current_v6", "candidate", "delta", "hits", "cost", "fallback")},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
