"""Read-only post-run integrity audit for frozen Policy-program regression v1.

No model calls, benchmark gold scoring, raw server errors or credential reads.
It verifies durable artifacts and declared report lineage, not NL correctness.
"""

from collections import Counter
import json
from pathlib import Path

from guardian_truth.cycle2.policy_semantics import load_policy_dataset
from guardian_truth.vnext.integrity import digest, file_digest, prediction_seal, verify_files
from guardian_truth.vnext.stage_policy_programs_v1 import summarize_programs

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/vnext"
PREFIX = "policy_programs_v1"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def verify_request_link(directory, stem, ordinal, telemetry, configuration_sha256):
    """Validate one persisted physical request against its case telemetry."""
    base = directory / f"{stem}_request_{ordinal:03d}"
    request, result = read(base.with_suffix(".json")), read(directory / (base.name + "_result.json"))
    if (request.get("configuration_sha256") != configuration_sha256
            or request.get("ordinal") != ordinal or result.get("request_sha256") != digest(request)
            or result.get("telemetry") != telemetry):
        raise ValueError("persisted request/result/case telemetry linkage mismatch")
    if telemetry.get("prompt_sha256") != request.get("prompt_sha256") or telemetry.get("schema_sha256") != request.get("schema_sha256"):
        raise ValueError("persisted prompt/schema hash differs from telemetry")
    if not all(key in telemetry for key in ("transport_status", "schema_status", "usage", "latency_ms")):
        raise ValueError("incomplete physical request diagnostics")
    return result


def audit(root=ROOT):
    root = Path(root).resolve()
    out = root / "outputs/vnext"
    paths = {key: out / f"{PREFIX}_{suffix}.json" for key, suffix in (
        ("freeze", "freeze"), ("predictions", "predictions"), ("seal", "prediction_seal"),
        ("report", "results"), ("failure_audit", "failure_audit"))}
    missing = [path.name for path in paths.values() if not path.is_file()]
    if missing:
        return {"status": "NOT_RUN_OR_INCOMPLETE", "missing": missing,
            "scope": "POST_RUN_ARTIFACT_INTEGRITY_ONLY_NOT_NL_CORRECTNESS_OR_CORE_GAIN"}
    frozen, rows, seal, report, failure = (read(paths[key]) for key in paths)
    errors = []
    errors.extend(verify_files(root, frozen["source_sha256"]))
    for relative, field in (("outputs/cycle2/policy_cases.json", "benchmark_sha256"),
            ("contracts/cycle2_policy_arms_v1.json", "baseline_contract_sha256"),
            ("outputs/vnext/provider_gate_v1.json", "gate_sha256")):
        if file_digest(root / relative) != frozen[field]:
            errors.append("FROZEN_INPUT_HASH:" + relative)
    case_ids = frozen["case_ids"]
    if len(case_ids) != 104 or len(set(case_ids)) != 104 or [row["case_id"] for row in rows] != case_ids:
        errors.append("EXACT_CASE_INVENTORY")
    else:
        expected = prediction_seal(rows, case_ids, architecture_commit=frozen["architecture_commit"],
            configuration_sha256=digest(frozen))
        if seal != expected:
            errors.append("PREDICTION_SEAL")
    for key, recorded in (("freeze", "freeze_sha256"), ("predictions", "predictions_sha256"),
            ("seal", "prediction_seal_sha256")):
        if report.get(recorded) != file_digest(paths[key]):
            errors.append("REPORT_" + recorded.upper())
    if (report.get("case_count") != len(rows)
            or failure.get("source_report_sha256") != file_digest(paths["report"])
            or failure.get("cases") != report.get("failure_taxonomy")
            or len(failure.get("cases", [])) != len(rows)):
        errors.append("REPORT_FAILURE_AUDIT_LINK")
    if len(rows) == 104:
        recalculated = summarize_programs(load_policy_dataset(root / "outputs/cycle2/policy_cases.json").cases, rows)
        if any(report.get(key) != value for key, value in recalculated.items()):
            errors.append("REPORT_METRICS_OR_CASE_TAXONOMY")
    configuration_sha256 = digest(frozen)
    request_count, remote_unknown = 0, 0
    for index, row in enumerate(rows):
        stem = f"{PREFIX}_case_{index:03d}"
        case_path = out / (stem + ".json")
        if not case_path.is_file() or read(case_path) != row or row.get("configuration_sha256") != configuration_sha256:
            errors.append("CASE_ROW_LINK:" + stem)
            continue
        for suffix, key in (("native", "native_request_telemetry"), ("p1", "p1_request_telemetry")):
            expected_requests = {f"{stem}_{suffix}_request_{ordinal:03d}.json"
                for ordinal in range(len(row[key]))}
            actual_requests = {path.name for path in out.glob(f"{stem}_{suffix}_request_*.json")
                if not path.name.endswith("_result.json")}
            if actual_requests != expected_requests:
                errors.append("REQUEST_INVENTORY:" + stem + ":" + suffix)
            for ordinal, telemetry in enumerate(row[key]):
                request_count += 1
                remote_unknown += telemetry.get("remote_outcome") == "UNKNOWN_NO_AUTOMATIC_RETRY"
                try:
                    verify_request_link(out, stem + "_" + suffix, ordinal, telemetry, configuration_sha256)
                except (OSError, KeyError, ValueError, json.JSONDecodeError):
                    errors.append("REQUEST_LINK:" + stem + ":" + suffix + ":" + str(ordinal))
    if request_count != report.get("provider", {}).get("combined", {}).get("request_records"):
        errors.append("REQUEST_TELEMETRY_COUNT")
    return {"status": "INTEGRITY_VALID" if not errors else "INTEGRITY_FAILED", "errors": errors,
        "case_count": len(rows), "physical_request_records": request_count,
        "unknown_remote_capture": remote_unknown,
        "semantic_coverage": report.get("semantic_coverage"),
        "schema_invalid": report.get("provider", {}).get("combined", {}).get("schema_invalid"),
        "failure_components": dict(Counter(component for row in failure.get("cases", [])
            for component in row.get("components", []))),
        "freeze_sha256": file_digest(paths["freeze"]), "report_sha256": file_digest(paths["report"]),
        "scope": "POST_RUN_ARTIFACT_INTEGRITY_ONLY_NOT_NL_CORRECTNESS_OR_CORE_GAIN"}


if __name__ == "__main__":
    print(json.dumps(audit(), ensure_ascii=False))
