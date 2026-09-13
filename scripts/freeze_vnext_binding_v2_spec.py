"""Freeze independent source specification before candidate fixes; zero API calls."""

import importlib.util
import json
from pathlib import Path
import subprocess

from guardian_truth.vnext.integrity import digest, file_digest, write_new

ROOT = Path(__file__).resolve().parents[1]
PATHS = (
    "benchmarks/vnext/binding_temporal_v2.spec.json",
    "benchmarks/vnext/binding_fixture_reference_v2.py",
    "docs/vnext/BINDING_TEMPORAL_V2_PROTOCOL.md",
    "tests/test_vnext_binding_fixture_reference_v2.py",
    "scripts/freeze_vnext_binding_v2_spec.py",
)


def main():
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch != "experiment/guardian-vnext-from-0199bf9":
        raise ValueError("independent vNext branch required")
    for relative in PATHS:
        subprocess.run(["git", "ls-files", "--error-unmatch", relative], cwd=ROOT, capture_output=True, check=True)
    if subprocess.run(["git", "diff", "--quiet", "HEAD", "--", *PATHS], cwd=ROOT).returncode:
        raise ValueError("commit source specification before freezing")
    spec = json.loads((ROOT / PATHS[0]).read_text(encoding="utf-8"))
    ids = [case["id"] for case in spec["cases"]]
    if len(ids) != 34 or len(set(ids)) != 34:
        raise ValueError("complete unique source-backed inventory required")
    module_spec = importlib.util.spec_from_file_location("binding_reference", ROOT / PATHS[1])
    reference = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(reference)
    rows, projected = [], []
    for case in spec["cases"]:
        executed = reference.execute_fixture(case["input"])
        result = reference.reference_query(executed)
        matches = result["truth"] == case["gold"]["truth"]
        if "binding_count" in case["gold"]:
            matches = matches and len(result["bindings"]) == case["gold"]["binding_count"]
        if not matches:
            raise ValueError("independent reference specification mismatch: " + case["id"])
        source = reference.candidate_input(executed)
        projected.append({"case_id": case["id"], "input_sha256": digest(source)})
        rows.append({"case_id": case["id"], "reference": result, "matches_specification": matches})
    result = {
        "schema_version": "guardian-binding-preimplementation-spec-freeze-v1",
        "scope": spec["scope"], "experiment": "binding_temporal_v2",
        "specification_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "case_ids": ids, "case_ids_sha256": digest(ids),
        "source_sha256": {relative: file_digest(ROOT / relative) for relative in PATHS},
        "candidate_inputs_sha256": digest(projected), "candidate_input_hashes": projected,
        "independent_reference_validation": {"case_count": 34, "matching_outcomes": 34, "cases": rows},
        "candidate_implementation": "NOT_RUN", "candidate_predictions": "NOT_RUN",
        "native_frontend_evaluation": "NOT_RUN", "core_certificate_validation": "NOT_ESTABLISHED",
        "api_requests": 0, "blind_gold_opened": False,
    }
    write_new(ROOT / "outputs/vnext/binding_temporal_v2_spec_freeze.json", result)
    print(json.dumps({"scope": spec["scope"], "reference_matching": "34/34", "candidate_predictions": "NOT_RUN", "api_requests": 0}))


if __name__ == "__main__":
    main()
