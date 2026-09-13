"""Audit frozen symbolic binding inputs without inventing trace/contracts/gold."""

import json
from pathlib import Path

from guardian_truth.vnext.integrity import digest, file_digest, verify_files, write_new

ROOT = Path(__file__).resolve().parents[1]


def main():
    benchmark_path = ROOT / "benchmarks/vnext/binding_temporal_v1.json"
    manifest_path = ROOT / "outputs/vnext/freeze_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if verify_files(ROOT, manifest["frozen_input_sha256"]):
        raise ValueError("frozen benchmark inputs changed")
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    if benchmark["cases_sha256"] != digest(benchmark["cases"]):
        raise ValueError("frozen case hash mismatch")
    cases = []
    for case in benchmark["cases"]:
        value = case["input"]
        events = value["events"]
        structured = all(isinstance(event, dict) and {"actor", "kind", "source"} <= set(event) for event in events)
        explicit_contracts = isinstance(value.get("trusted_contracts"), list) and bool(value["trusted_contracts"])
        complete_premise = value.get("history_complete") is True and bool(value.get("completeness_basis"))
        missing = []
        if not structured:
            missing.append("adapter-owned event actor/kind/source/pairing/entity/time records")
        if not explicit_contracts:
            missing.append("version/schema-bound source-backed tool contracts and conditional result semantics")
        if not complete_premise:
            missing.append("input-owned history/candidate completeness premise; gold.complete_search is not evidence")
        cases.append({"case_id": case["case_id"], "family": case["family"], "input_sha256": digest(value),
            "event_count": len(events), "structured_trace": structured, "trusted_contracts_supplied": explicit_contracts,
            "completeness_premise_supplied": complete_premise,
            "grounding_status": "NOT_ESTABLISHED" if missing else "STRUCTURAL_INPUTS_PRESENT_NOT_SEMANTIC_PROOF",
            "missing": missing,
            "components": ["EVIDENCE_COMPLETENESS", "SOURCE_BINDING", "TOOL_EFFECT"] if missing else [],
            "core_prediction": "NOT_RUN", "reference_verdict_adjudication": "NOT_ESTABLISHED_FROM_SYMBOLIC_INPUTS"})
    report = {"scope": "FROZEN_BINDING_INPUT_SUFFICIENCY_AUDIT_NOT_BINDER_OR_CORE_EVALUATION",
        "benchmark_sha256": file_digest(benchmark_path), "manifest_sha256": file_digest(manifest_path),
        "case_count": len(cases), "distinct_symbolic_inputs": len({digest({key: value for key, value in case["input"].items()
            if key != "variant"}) for case in benchmark["cases"]}),
        "source_grounding_not_established": sum(case["grounding_status"] == "NOT_ESTABLISHED" for case in cases),
        "api_requests": 0, "core_predictions": "NOT_RUN", "blind_gold_opened": False,
        "metrics": "NOT_ESTABLISHED_NO_EXECUTABLE_BINDING_EVALUATION",
        "reference_limit": "tool_reference_v1.py adjudicates archive version/status/prior-state tuples, not these arbitrary symbolic traces",
        "next": "separate source-backed executable trace/contract/query extension before implementing missing temporal primitives",
        "cases": cases}
    write_new(ROOT / "outputs/vnext/binding_temporal_v1_source_audit.json", report)
    print(json.dumps({key: report[key] for key in ("scope", "case_count", "source_grounding_not_established", "api_requests")}))


if __name__ == "__main__":
    main()
