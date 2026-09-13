"""Audit independent fixture reference against frozen preimplementation statuses."""

import importlib.util
import json
from pathlib import Path

from guardian_truth.vnext.integrity import file_digest, verify_files, write_new

ROOT = Path(__file__).resolve().parents[1]


def main():
    freeze_path = ROOT / "outputs/vnext/goal_alignment_v3_mechanisms_v1_spec_freeze.json"
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    if verify_files(ROOT, freeze["source_sha256"]):
        raise ValueError("preimplementation source specification changed")
    spec_path = ROOT / "benchmarks/vnext/goal_alignment_v3_mechanisms_v1.spec.json"
    reference_path = ROOT / "benchmarks/vnext/goal_alignment_reference_v1.py"
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    module_spec = importlib.util.spec_from_file_location("independent_goal_fixture", reference_path)
    reference = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(reference)
    cases = []
    for case in spec["cases"]:
        safe = {key: value for key, value in case.items() if key not in {"id", "family", "reference", "meaning_universe"}}
        result = reference.evaluate_fixture(spec, safe)
        cases.append({"case_id": case["id"], "family": case["family"], "result": result,
            "expected_status": case["reference"]["status"],
            "matches": result["status"] == case["reference"]["status"]})
    report = {"scope": "INDEPENDENT_FIXTURE_REFERENCE_VALIDATION_NOT_GOAL_V3_EVALUATION",
        "spec_freeze_sha256": file_digest(freeze_path), "spec_sha256": file_digest(spec_path),
        "reference_sha256": file_digest(reference_path), "reference_premises_sha256": reference.SOURCE_PREMISES_SHA256,
        "case_count": len(cases), "matching_statuses": sum(case["matches"] for case in cases),
        "api_requests": 0, "v3_predictions": "NOT_RUN", "blind_gold_opened": False, "cases": cases}
    write_new(ROOT / "outputs/vnext/goal_alignment_v3_reference_validation_v1.json", report)
    print(json.dumps({key: report[key] for key in ("scope", "case_count", "matching_statuses", "api_requests")}))
    return 0 if all(case["matches"] for case in cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
