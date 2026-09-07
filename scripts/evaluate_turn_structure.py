"""Replay the exact turn-structure precheck against a frozen semantic run."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from guardian_truth.benchmarking import Example, Score, metrics, paired_comparison
from guardian_truth.cli import read_rows, validate_rows
from guardian_truth.pipeline import Detector


TARGET_CODES = {"multiple_tool_calls_in_turn", "mixed_text_and_tool_call"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("valid.parquet"))
    parser.add_argument("--baseline-audit", type=Path,
                        default=Path("outputs/claim_gate_20b_full/audit.jsonl"))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir / "report.json"
    if output.exists():
        parser.error("Refusing to overwrite an existing report")
    rows = read_rows(args.input)
    validate_rows(rows)
    baseline = [json.loads(line) for line in
                args.baseline_audit.read_text(encoding="utf-8").splitlines()]
    if [str(row["id"]) for row in rows] != [row["id"] for row in baseline]:
        parser.error("Baseline and input row order/IDs differ")
    detector = Detector()
    predictions = []
    hits = []
    short_circuited = set()
    for row, old in zip(rows, baseline):
        review = detector.review(row["prompt"], row["response"])
        findings = [finding for finding in review.findings if finding.code in TARGET_CODES]
        before = old["strict"]["label"]
        after = int(bool(findings) or before == 1)
        predictions.append(after)
        if findings:
            short_circuited.add(old["id"])
            hits.append({
                "id": old["id"], "gold": old["label"], "before": before,
                "after": after, "already_mechanical": old["skipped_mechanical"],
                "codes": [finding.code for finding in findings],
                "sources": [[{"document": source.document, "start": source.start,
                               "end": source.end} for source in finding.sources]
                            for finding in findings],
            })
    labels = [row["label"] for row in baseline]
    old_predictions = [row["strict"]["label"] for row in baseline]
    examples = [Example(str(row["id"]), row["prompt"], row["response"],
                        int(row["label"]),
                        source_id=str(row["id"]).split("::", 1)[0])
                for row in rows]
    comparison = paired_comparison(
        examples,
        [Score(str(row["id"]), float(value)) for row, value in zip(rows, old_predictions)],
        [Score(str(row["id"]), float(value)) for row, value in zip(rows, predictions)],
        bootstrap_samples=1000, seed=0)
    newly_short = [row for row in baseline
                   if row["id"] in short_circuited and not row["skipped_mechanical"]]
    result = {
        "configuration": {
            "experiment": "offline_exact_precheck_replay_over_frozen_semantic_baseline",
            "rows": len(rows), "target_codes": sorted(TARGET_CODES),
            "input_sha256": hashlib.sha256(args.input.read_bytes()).hexdigest(),
            "baseline_audit_sha256": hashlib.sha256(args.baseline_audit.read_bytes()).hexdigest(),
            "source_sha256": {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                              for path in (Path("src/guardian_truth/checks.py"),
                                           Path("src/guardian_truth/pipeline.py"),
                                           Path(__file__))},
            "labels_or_explanations_used_by_precheck": False,
        },
        "baseline": metrics(labels, old_predictions),
        "candidate": metrics(labels, predictions),
        "delta": {
            "f1": metrics(labels, predictions)["f1"] - metrics(labels, old_predictions)["f1"],
            "precision": metrics(labels, predictions)["precision"] - metrics(labels, old_predictions)["precision"],
            "recall": metrics(labels, predictions)["recall"] - metrics(labels, old_predictions)["recall"],
        },
        "paired_comparison": comparison,
        "hits": hits,
        "changed": [item for item in hits if item["before"] != item["after"]],
        "hit_gold_counts": dict(Counter(item["gold"] for item in hits)),
        "new_mechanical_short_circuits": len(newly_short),
        "cost": {
            "additional_llm_calls": 0,
            "baseline_logical_calls": sum(not row["skipped_mechanical"] for row in baseline),
            "candidate_logical_calls": (sum(not row["skipped_mechanical"] for row in baseline)
                                         - len(newly_short)),
            "baseline_http_attempts": 99,
            "candidate_http_attempts": None,
            "http_attempt_note": "Per-row HTTP attempts were not stored by the frozen baseline; exact savings cannot be reconstructed.",
            "baseline_reported_tokens": sum(row["review"].get("semantic_usage", {}).get("total_tokens", 0)
                                             for row in baseline),
            "candidate_reported_tokens": sum(row["review"].get("semantic_usage", {}).get("total_tokens", 0)
                for row in baseline) - sum(row["review"].get("semantic_usage", {}).get("total_tokens", 0)
                                           for row in newly_short),
            "basis": "Exact replay: rows newly caught by the precheck would bypass the unchanged semantic judge.",
        },
        "fallback": {
            "baseline": sum(row["strict"]["used_fallback"] for row in baseline),
            "candidate": sum(row["strict"]["used_fallback"] and row["id"] not in short_circuited
                             for row in baseline),
        },
        "limitations": [
            "The 46-row validation file is inspected development data, not an independent hidden test.",
            "Candidate semantic outputs are replayed from the frozen baseline; only deterministic preemption changes.",
            "The rule parser intentionally recognizes only narrow English system-policy formulations.",
        ],
    }
    args.output_dir.mkdir(parents=True, exist_ok=False)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(json.dumps({key: result[key] for key in
                      ("baseline", "candidate", "delta", "hit_gold_counts",
                       "new_mechanical_short_circuits", "cost", "fallback")},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
