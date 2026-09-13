"""Add a detailed, immutable field audit AFTER validating the sealed v1 run."""

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from guardian_truth.vnext.integrity import digest, file_digest, prediction_seal, write_new
from scripts.vnext_claim_scoring import score_case


def main():
    output = ROOT / "outputs/vnext"
    prefix = "claim_graph_v1"
    freeze = json.loads((output / (prefix + "_freeze.json")).read_text(encoding="utf-8"))
    rows = json.loads((output / (prefix + "_predictions.json")).read_text(encoding="utf-8"))
    seal = json.loads((output / (prefix + "_prediction_seal.json")).read_text(encoding="utf-8"))
    if seal != prediction_seal(rows, freeze["case_ids"], architecture_commit=freeze["architecture_commit"],
                               configuration_sha256=digest(freeze)):
        raise ValueError("prediction seal invalid; no controlled gold joined")
    benchmark_path = ROOT / "benchmarks/vnext/claim_graph_v1.json"
    if file_digest(benchmark_path) != freeze["benchmark_sha256"]:
        raise ValueError("benchmark hash changed")
    report_path = output / (prefix + "_results.json")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    by_id = {row["case_id"]: row for row in rows}
    cases = []
    for case in benchmark["cases"]:
        row = by_id[case["case_id"]]
        score = score_case(case, row["prediction"])
        nodes = row["prediction"]["vnext"]["claims"]
        mismatches = []
        for field in score["fields"]:
            if field["arm"] != "vnext" or not field["eligible"] or field["correct"]:
                continue
            offset = field["offsets"]
            node = next((node for node in nodes if offset is None or [node["span"]["start"], node["span"]["end"]] == offset), {})
            expected = case["gold"] if offset is None else next(item for item in case["gold"]["spans"]
                if [item["start"], item["end"]] == offset)
            mismatches.append({"field": field["field"], "offsets": offset,
                "expected": expected[field["field"]], "actual": node.get(field["field"]),
                "interpretation": "EXACT_ANNOTATION_MISMATCH_SEMANTIC_EQUIVALENCE_NOT_ADJUDICATED"})
        telemetry = row["vnext_request_telemetry"]
        cases.append({"case_id": case["case_id"], "family": case["family"], "response": case["input"]["response"],
            "components": next(item["components"] for item in report["failure_taxonomy"] if item["case_id"] == case["case_id"]),
            "field_mismatches": mismatches, "failed_requests": [{"task": item["task"], "transport_status": item["transport_status"],
                "schema_status": item["schema_status"], "error_category": item["error_category"]}
                for item in telemetry if item["transport_status"] != "SUCCESS" or item["schema_status"] != "VALID"]})
    destination = output / (prefix + "_detailed_audit.json")
    write_new(destination, {"schema_version": "guardian-vnext-claim-field-audit-v1", "experiment": prefix,
        "source_report_sha256": file_digest(report_path), "prediction_seal_sha256": file_digest(output / (prefix + "_prediction_seal.json")),
        "case_count": len(cases), "scope": "controlled dev exact-field audit; no blind data and no semantic-equivalence upgrade", "cases": cases})
    print(json.dumps({"case_count": len(cases), "field_mismatches": sum(len(case["field_mismatches"]) for case in cases),
        "failed_requests": sum(len(case["failed_requests"]) for case in cases), "api_requests": 0}))


if __name__ == "__main__":
    main()
