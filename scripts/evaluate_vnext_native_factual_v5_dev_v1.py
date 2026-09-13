"""Freeze/replay/run conditional native factual integration; never a Core verdict.

No network admission before the preceding frozen Policy report AND audit exist.
Source execution produces tool traces; reference truth is joined only after seal.
"""

import argparse
from collections import Counter
from dataclasses import asdict, replace
import importlib.util
import json
from pathlib import Path
import subprocess

from guardian_truth.llm_client import ChatClient, ClientConfig
from guardian_truth.runtime import provider_config
from guardian_truth.settings import load_env_file
from guardian_truth.vnext.experiment import PersistedSemanticBackend, ProviderPause
from guardian_truth.vnext.factual_envelope_v5 import analyze_envelope_factual_v5
from guardian_truth.vnext.integrity import digest, file_digest, prediction_seal, verify_files, write_new
from guardian_truth.vnext.latency import percentile
from guardian_truth.vnext.semantic_v2 import DiagnosticSemanticBackend
from guardian_truth.vnext.source_envelope_v4 import SourceFrame
from guardian_truth.vnext.types import ClaimKind, Disposition, Span

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/vnext"
PREFIX = "native_factual_v5_dev_v1"
SPEC = ROOT / "benchmarks/vnext/native_factual_v5_dev_v1.spec.json"
CONFIG = {"scope": "CONDITIONAL_NATIVE_METHOD_INTEGRATION_DEV_NOT_CORE_OR_BLIND",
    "provider": "bai", "model": "qwen3.8-flash", "timeout_seconds": 180,
    "max_output_tokens": 2048, "max_retries": 0, "interval_seconds": 10,
    "temperature": 0, "response_format_mode": "none", "escalations": 0,
    "truth": "unanimous material method span primitives; unsupported/empty/blocked is UNKNOWN",
    "binary_adapter": "NOT_APPLICABLE", "cost": "NOT_AUDITED",
    "admission": "previous frozen Policy report and per-case audit must exist"}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def load(relative, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture_input(spec, case):
    initial = [dict(row) for row in spec["initial"]]
    if case.get("initial_archived"):
        initial[0]["archived"] = True
    return {"initial": initial, "steps": [{"record_id": "V-901", **row} for row in case["steps"]],
        "history_complete": case.get("history_complete", True),
        "query": {"kind": "METHOD_HISTORY", "entity": case.get("entity", {"mode": "id", "value": "V-901"}),
            "operation": case["operation"], "actor": case.get("actor", "assistant"), "expected": case["expected"]}}


def source_input(spec, case, reference):
    return {"source": reference.candidate_input(reference.execute_fixture(fixture_input(spec, case))),
        "response": case["response"]}


def conditional_truth(analysis):
    material = [claim for claim in analysis.graph.claims if claim.disposition is not Disposition.NON_VERIFIABLE]
    if not material or analysis.diagnostics.blocked_claims or not analysis.method_receipt_valid:
        return "UNKNOWN"
    if any(claim.kind not in {ClaimKind.ACTION_COMPLETED, ClaimKind.ABSENCE} for claim in material):
        return "UNKNOWN"
    ids = {claim.claim_id for claim in material}
    values = {row.value.value for row in analysis.method_evidence if row.claim_id in ids}
    return next(iter(values)) if len(values) == 1 else "UNKNOWN"


def assert_policy_admission():
    report_path = OUT / "policy_programs_v1_results.json"
    audit_path = OUT / "policy_programs_v1_failure_audit.json"
    if not report_path.exists() or not audit_path.exists():
        raise ValueError("Policy frozen evaluation and audit must complete before another API batch")
    report, audit = read(report_path), read(audit_path)
    cases = audit.get("cases", [])
    if (report["case_count"] != 104 or len(cases) != 104
            or len({row["case_id"] for row in cases}) != 104
            or cases != report["failure_taxonomy"]
            or audit["source_report_sha256"] != file_digest(report_path)):
        raise ValueError("preceding Policy report/audit incomplete or mismatched")


def provider_summary(records):
    captured = [row for row in records if row.get("remote_outcome") != "UNKNOWN_NO_AUTOMATIC_RETRY"]
    latencies = [row["latency_ms"] for row in captured]
    return {"requests": len(records),
        "unknown_remote_capture": len(records) - len(captured),
        "transport_success": sum(row["transport_status"] == "SUCCESS" for row in records),
        "schema_valid": sum(row["schema_status"] == "VALID" for row in records),
        "schema_invalid": sum(row["schema_status"] == "INVALID" for row in records),
        "latency_ms_p50": percentile(latencies, .5), "latency_ms_p95": percentile(latencies, .95),
        "token_usage": {key: sum(row.get("usage", {}).get(key, 0) for row in records)
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")}, "cost": "NOT_AUDITED"}


def freeze():
    spec = read(SPEC)
    reference = load("benchmarks/vnext/binding_fixture_reference_v2.py", "native_dev_source")
    paths = sorted(path.relative_to(ROOT).as_posix() for path in (ROOT / "src/guardian_truth").rglob("*.py"))
    paths += ["scripts/evaluate_vnext_native_factual_v5_dev_v1.py", SPEC.relative_to(ROOT).as_posix(),
        "benchmarks/vnext/binding_fixture_reference_v2.py", "benchmarks/vnext/binding_fixture_adapter_v2.py",
        "tests/test_vnext_native_factual_dev_protocol_v1.py"]
    for path in paths:
        subprocess.run(["git", "ls-files", "--error-unmatch", path], cwd=ROOT, capture_output=True, check=True)
    if subprocess.run(["git", "diff", "--quiet", "HEAD", "--", *paths], cwd=ROOT).returncode:
        raise ValueError("commit candidate before freeze")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    write_new(OUT / (PREFIX + "_freeze.json"), {"architecture_commit": commit, "configuration": CONFIG,
        "configuration_sha256": digest(CONFIG), "source_sha256": {path: file_digest(ROOT / path) for path in paths},
        "case_ids": [case["id"] for case in spec["cases"]],
        "case_input_sha256": [digest(source_input(spec, case, reference)) for case in spec["cases"]],
        "design_boundary": spec["scope"], "blind_gold_opened": False})
    print(json.dumps({"status": "FROZEN_NOT_RUN", "cases": len(spec["cases"]), "api_requests": 0}))


def run(env_file):
    assert_policy_admission()
    frozen = read(OUT / (PREFIX + "_freeze.json"))
    if verify_files(ROOT, frozen["source_sha256"]) or frozen["configuration_sha256"] != digest(CONFIG):
        raise ValueError("frozen candidate changed")
    if (OUT / (PREFIX + "_results.json")).exists():
        raise FileExistsError("joined experiment immutable")
    spec = read(SPEC)
    reference = load("benchmarks/vnext/binding_fixture_reference_v2.py", "native_dev_source")
    adapter = load("benchmarks/vnext/binding_fixture_adapter_v2.py", "native_dev_adapter")
    load_env_file(env_file)
    config = provider_config(ClientConfig(timeout_seconds=180, max_output_tokens=2048, max_retries=0,
        response_format_mode="none"), "bai", model="qwen3.8-flash")
    live, rows = [], []
    delegate = DiagnosticSemanticBackend(ChatClient(config), interval_seconds=10, checkpoint=live.append)
    for index, case in enumerate(spec["cases"]):
        source = source_input(spec, case, reference)
        if digest(source) != frozen["case_input_sha256"][index]:
            raise ValueError("source input projection changed")
        path = OUT / (PREFIX + f"_case_{index:03d}.json")
        if path.exists():
            row = read(path)
            if row["case_id"] != case["id"] or row["freeze_sha256"] != digest(frozen):
                raise ValueError("cached case changed")
        else:
            envelope, snapshots, registry, methods, _ = adapter.make_context(source["source"])
            response = source["response"]
            span = Span("response", 0, len(response))
            envelope = replace(envelope, response=response, frames=envelope.frames + (SourceFrame(span, span, "assistant", "text"),))
            backend = PersistedSemanticBackend(delegate, OUT, PREFIX + f"_case_{index:03d}",
                configuration_sha256=digest(frozen), live_records=live)
            result = analyze_envelope_factual_v5(envelope, snapshots, registry, methods, backend)
            row = {"case_id": case["id"], "freeze_sha256": digest(frozen), "input_sha256": digest(source),
                "conditional_truth": conditional_truth(result), "graph": asdict(result.graph),
                "method_evidence": [asdict(item) for item in result.method_evidence],
                "method_receipt": asdict(result.method_receipt) if result.method_receipt else None,
                "method_receipt_valid": result.method_receipt_valid, "diagnostics": asdict(result.diagnostics),
                "telemetry": backend.records, "core_status": "NOT_EVALUATED"}
            write_new(path, row)
        rows.append(row)
        print(json.dumps({"completed": len(rows), "total": len(spec["cases"])}), flush=True)
    ids = [row["case_id"] for row in rows]
    if ids != frozen["case_ids"]:
        raise ValueError("exact full case inventory required")
    for suffix, value in (("_predictions.json", rows), ("_prediction_seal.json", prediction_seal(rows, ids,
            architecture_commit=frozen["architecture_commit"], configuration_sha256=digest(frozen)))):
        path = OUT / (PREFIX + suffix)
        if path.exists():
            if digest(read(path)) != digest(value):
                raise ValueError("persisted seal changed")
        else:
            write_new(path, value)
    # Only after full predictions + seal are durable, join independent truth.
    scored = []
    for case, row in zip(spec["cases"], rows):
        gold = reference.reference_query(reference.execute_fixture(fixture_input(spec, case)))
        failures = []
        if gold["truth"] != row["conditional_truth"]:
            failures.append("NATIVE_SEMANTICS_OR_BINDING")
        if not row["method_receipt_valid"]:
            failures.append("CERTIFICATE")
        scored.append({"case_id": case["id"], "reference": gold, "conditional_truth": row["conditional_truth"],
            "correct": not failures, "failure_components": failures})
    records = [record for row in rows for record in row["telemetry"]]
    report = {"scope": CONFIG["scope"], "case_count": len(rows), "cases": scored,
        "conditional_truth_correct": sum(row["correct"] for row in scored),
        "conditional_truth_distribution": dict(Counter(row["conditional_truth"] for row in rows)),
        "method_receipts_valid": sum(row["method_receipt_valid"] for row in rows),
        "telemetry": records, "provider": provider_summary(records),
        "semantic_coverage": dict(Counter(item["coverage"] for row in rows for item in row["method_evidence"])),
        "unresolved_reason_distribution": dict(Counter(reason for row in rows
            for reason in [row["diagnostics"]["primary_reason"], *row["diagnostics"]["contributing_reasons"]] if reason)),
        "core_resolution": "NOT_EVALUATED", "binary_f1": None, "blind_gold_opened": False,
        "freeze_sha256": file_digest(OUT / (PREFIX + "_freeze.json")),
        "predictions_sha256": file_digest(OUT / (PREFIX + "_predictions.json")),
        "seal_sha256": file_digest(OUT / (PREFIX + "_prediction_seal.json"))}
    write_new(OUT / (PREFIX + "_results.json"), report)
    write_new(OUT / (PREFIX + "_failure_audit.json"), {"source_report_sha256": file_digest(OUT / (PREFIX + "_results.json")), "cases": scored})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("freeze", "run"))
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args()
    if args.phase == "run" and args.env_file is None:
        parser.error("--env-file required")
    try:
        freeze() if args.phase == "freeze" else run(args.env_file)
    except ProviderPause as error:
        print(json.dumps({"status": "PROVIDER_PAUSED", "reason": str(error)}))
        raise SystemExit(2)
