"""Evaluate a shadow hard gate from frozen accusation-verifier outputs."""

import argparse
from collections import defaultdict
import json
from pathlib import Path

from guardian_truth.benchmarking import metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calls", type=Path, required=True)
    parser.add_argument("--baseline-audit", type=Path,
                        default=Path("outputs/claim_gate_20b_full/audit.jsonl"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Refusing to overwrite output")
    calls = [json.loads(line) for line in args.calls.read_text(encoding="utf-8").splitlines()]
    if not calls or len({row["id"] for row in calls}) != len(calls):
        parser.error("Invalid or duplicate verifier calls")
    by_row = defaultdict(list)
    for call in calls:
        by_row[call["row_id"]].append(call)
    baseline = [json.loads(line) for line in
                args.baseline_audit.read_text(encoding="utf-8").splitlines()]
    semantic_positive = {row["id"] for row in baseline
                         if not row["skipped_mechanical"] and row["strict"]["label"] == 1}
    if set(by_row) != semantic_positive:
        parser.error("Verifier rows do not equal all baseline semantic-positive rows")
    changed = []
    predictions = []
    for row in baseline:
        before = row["strict"]["label"]
        after = before
        if row["id"] in by_row:
            # Invalid/error verdicts cannot prove an accusation.  This is the
            # deliberately conservative hard-gate semantics being tested.
            after = int(any(call["status"] == "valid" and call["relation"] == "ENTAILED"
                            for call in by_row[row["id"]]))
        predictions.append(after)
        if after != before:
            changed.append({"id": row["id"], "gold": row["label"],
                            "before": before, "after": after,
                            "verifier_relations": [call["relation"] if call["status"] == "valid"
                                                   else "INVALID_OR_ERROR"
                                                   for call in by_row[row["id"]]]})
    labels = [row["label"] for row in baseline]
    result = {
        "baseline": metrics(labels, [row["strict"]["label"] for row in baseline]),
        "candidate": metrics(labels, predictions),
        "changed": changed,
        "corrected": sum(item["after"] == item["gold"] for item in changed),
        "regressed": sum(item["before"] == item["gold"] for item in changed),
        "verifier": {
            "calls": len(calls),
            "valid": sum(call["status"] == "valid" for call in calls),
            "http_attempts": sum(call["http_attempts_reserved"] for call in calls),
            "reported_tokens": sum(call.get("usage", {}).get("total_tokens", 0)
                                   for call in calls),
        },
        "limitations": [
            "Inspected development data and audited accusations; not hidden-test evidence.",
            "The verifier sees only evidence cited by the one-shot accusation.",
            "A rejected accusation can coexist with a different real row error.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
