#!/usr/bin/env python3
"""Run the offline V9 falsification benchmark; no model API is used."""

import argparse
import json
from pathlib import Path

from guardian_truth.outer_benchmarking import (
    auxiliary_experiments, evaluate_real_rules, evaluate_row_slice,
)


def validate_sources(cases, parquet_path):
    import pandas as pd

    frame = pd.read_parquet(parquet_path, columns=["id", "prompt", "response"])
    texts = {row.id: {"p": row.prompt, "r": row.response}
             for row in frame.itertuples(index=False)}
    issues = []
    span_count = 0
    seen = set()
    for case in cases:
        row_id = case.get("row_id")
        if row_id in seen:
            issues.append(f"{row_id}:duplicate")
        seen.add(row_id)
        documents = texts.get(row_id)
        if documents is None:
            issues.append(f"{row_id}:missing_row")
            continue
        for index, source in enumerate(case.get("sources", ())):
            span_count += 1
            document = documents.get(source.get("d")) if isinstance(source, dict) else None
            start = source.get("s") if isinstance(source, dict) else None
            end = source.get("e") if isinstance(source, dict) else None
            if (not isinstance(document, str) or type(start) is not int or type(end) is not int
                    or not 0 <= start < end <= len(document) or not document[start:end]):
                issues.append(f"{row_id}:source_{index}")
    return {"rows": len(cases), "unique_rows": len(seen), "spans": span_count,
            "all_valid": not issues, "issues": issues}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rules", default="experiments/v8_typed_rules_benchmark_v3.json")
    parser.add_argument("--rows", default="experiments/v9_outer_semantics_benchmark.json")
    parser.add_argument("--typed-report", default="outputs/v8_typed_sentinels4_r3/report.json")
    parser.add_argument("--parquet", default="valid.parquet")
    parser.add_argument("--output", default="docs/v9_outer_semantics_result.json")
    args = parser.parse_args()
    rules = json.loads(Path(args.rules).read_text(encoding="utf-8"))
    rows = json.loads(Path(args.rows).read_text(encoding="utf-8"))
    typed_path = Path(args.typed_report)
    typed = json.loads(typed_path.read_text(encoding="utf-8")) if typed_path.exists() else None
    rules_result = evaluate_real_rules(rules["cases"])
    rows_result = evaluate_row_slice(rows["cases"])
    auxiliary = auxiliary_experiments()
    source_validation = validate_sources(rows["cases"], Path(args.parquet))
    if not source_validation["all_valid"]:
        raise SystemExit(f"Invalid frozen sources: {source_validation['issues']}")
    result = {
        "schema_version": 1,
        "scope": "offline shadow falsification; no production or contest predictions changed",
        "real_rule_construction_test": rules_result,
        "real_row_invariant_test": rows_result,
        "auxiliary_experiments": auxiliary,
        "source_validation": source_validation,
        "comparison_evidence": {
            "A_current_production": rows.get("baseline_aggregate"),
            "B_existing_free_formalization": ({
                "artifact": str(typed_path),
                "scope": "network-limited four-rule sentinel; not row F1",
                "metrics": typed["by_method"]["A"],
            } if typed else {"artifact": str(typed_path), "available": False}),
            "C_typed_slots_strict_schema": ({
                "artifact": str(typed_path),
                "scope": "network-limited four-rule sentinel; not row F1",
                "metrics": typed["by_method"]["C"],
            } if typed else {"artifact": str(typed_path), "available": False}),
            "D_outer_semantics": {
                "formalization_feature_coverage": rules_result["formalization_feature_coverage"],
                "gold_audit_gate_passed_real_rules": rules_result["gold_audit_gate_passed_cases"],
                "automatic_new_semantic_strict_verdicts": 0,
                "row_determinacy_exact_controls_only": rows_result["D_E_determinacy"],
                "confident_wrong_among_strict": rows_result["D_E_confident_wrong"],
            },
            "E_outer_plus_metamorphic": {
                "same_real_row_result_as_D": True,
                "metamorphic_sensitivity": auxiliary["metamorphic"]["sensitivity"],
            },
        },
    }
    output = Path(args.output)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "rule_feature_coverage": result["real_rule_construction_test"]["formalization_feature_coverage"],
        "gold_audit_gate_passed_rules": result["real_rule_construction_test"]["gold_audit_gate_passed_cases"],
        "row_determinacy": result["real_row_invariant_test"]["D_E_determinacy"],
        "metamorphic_sensitivity": result["auxiliary_experiments"]["metamorphic"]["sensitivity"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
