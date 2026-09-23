"""Compare input transport coverage without reading labels or explanations.

This is a diagnostic for the public competition sample and the hotel contrast
suite. It does not score hallucination detection or infer policy semantics.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from guardian_truth.parsing import parse_catalog, parse_events  # noqa: E402
from guardian_truth.pipeline import Detector  # noqa: E402


def read_cases(path: Path):
    if path.suffix == ".parquet":
        import pandas as pd

        for row in pd.read_parquet(path, columns=["id", "prompt", "response"]).to_dict("records"):
            yield row
        return
    csv.field_size_limit(2**31 - 1)
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            yield {key: row[key] for key in ("id", "prompt", "response")}


def audit(path: Path):
    detector = Detector()
    cases = []
    counts = Counter()
    for row in read_cases(path):
        history = parse_events(row["prompt"], "prompt")
        candidate = parse_events(row["response"], "response")
        catalog = parse_catalog(history, row["prompt"])
        review = detector.review(row["prompt"], row["response"])
        results = [event for event in history if event.kind == "result"]
        target_calls = [event for event in candidate if event.kind == "call"]
        item = {
            "id": row["id"],
            "catalog_complete": catalog.complete,
            "catalog_issues": catalog.issues,
            "declared_tools": len(catalog.tools),
            "history_results": len(results),
            "history_results_without_name": sum(not event.name for event in results),
            "candidate_calls": len(target_calls),
            "candidate_calls_without_name": sum(not event.name for event in target_calls),
            "mechanical_findings": len(review.findings),
            "review_status": review.status,
        }
        cases.append(item)
        counts["cases"] += 1
        counts["catalog_complete"] += int(catalog.complete)
        counts["history_results"] += item["history_results"]
        counts["history_results_without_name"] += item["history_results_without_name"]
        counts["candidate_calls"] += item["candidate_calls"]
        counts["candidate_calls_without_name"] += item["candidate_calls_without_name"]
        counts["cases_with_mechanical_findings"] += int(bool(review.findings))
        counts["unknown_reviews"] += int(review.status == "unknown")
    return {"input": str(path.relative_to(ROOT)), "counts": dict(counts), "cases": cases}


def main():
    inputs = {
        "public46": ROOT / "valid.parquet",
        "hotel20": ROOT / "outputs/searh_23/contrast_hotel/cases.csv",
    }
    result = {name: audit(path) for name, path in inputs.items()}
    output = ROOT / "outputs/searh_23/transport_coverage_audit.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for name, item in result.items():
        print(name, item["counts"])
    print(output)


if __name__ == "__main__":
    main()
