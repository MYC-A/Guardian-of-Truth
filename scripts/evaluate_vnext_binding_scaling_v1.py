"""Frozen event-count scaling of the existing candidate; no API/blind gold."""

import argparse
from dataclasses import asdict
import importlib.util
import json
from pathlib import Path
import subprocess
import time

from guardian_truth.vnext.integrity import digest, file_digest, prediction_seal, verify_files, write_new
from guardian_truth.vnext.source_envelope_v4 import normalize_envelope
from guardian_truth.vnext.temporal_certificate_v4 import make_temporal_certificate, validate_temporal_certificate
from guardian_truth.vnext.temporal_queries_v4 import TemporalQueryIndex

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/vnext"
SPEC = "benchmarks/vnext/binding_scaling_v1.spec.json"
SCRIPT = "scripts/evaluate_vnext_binding_scaling_v1.py"
STEM = "binding_scaling_v1"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def load(relative, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def inputs(spec):
    for size in spec["sizes"]:
        for template in spec["templates"]:
            if template["id"] == "mutation-count":
                steps = [{"operation": "archive", "version": template["tool_version"]} for _ in range((size - 4) // 2)]
            else:
                steps = [{"kind": "text", "text": template["text_body"]} for _ in range(size - 4)]
            yield {"case_id": "scale:" + str(size) + ":" + template["id"], "event_count": size,
                "template": template["id"], "input": {"steps": steps + [{"operation": "read"}], "query": template["query"]}}


def freeze():
    candidate_path = OUT / "binding_temporal_v2_freeze.json"
    candidate = read(candidate_path)
    if verify_files(ROOT, candidate["source_sha256"]):
        raise ValueError("existing frozen candidate changed")
    for relative in (SPEC, SCRIPT):
        subprocess.run(["git", "ls-files", "--error-unmatch", relative], cwd=ROOT, capture_output=True, check=True)
    if subprocess.run(["git", "diff", "--quiet", "HEAD", "--", SPEC, SCRIPT], cwd=ROOT).returncode:
        raise ValueError("commit scaling inputs and runner before freeze")
    spec = read(ROOT / SPEC)
    values = list(inputs(spec))
    if len(values) != 9 or spec["sizes"] != [100, 1000, 10000]:
        raise ValueError("complete required size/template inventory needed")
    config = {"scope": spec["scope"], "candidate": "frozen temporal queries v4",
        "api_requests": 0, "timing": "single-run stage timings, not population latency or native Core throughput",
        "world_scope": "typed explicit executable fixture; independent primitive certificates only",
        "candidate_fixes": "NONE; next version only after full report/audit"}
    artifact = {"schema_version": "guardian-binding-scaling-freeze-v1",
        "architecture_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "candidate_freeze_sha256": file_digest(candidate_path), "candidate_architecture_commit": candidate["architecture_commit"],
        "source_sha256": {**candidate["source_sha256"], SPEC: file_digest(ROOT / SPEC), SCRIPT: file_digest(ROOT / SCRIPT)},
        "case_ids": [value["case_id"] for value in values],
        "input_hashes": [{"case_id": value["case_id"], "input_sha256": digest(value["input"])} for value in values],
        "configuration": config, "configuration_sha256": digest(config), "candidate_evaluation": "NOT_RUN"}
    write_new(OUT / (STEM + "_freeze.json"), artifact)
    print(json.dumps({"status": "SCALING_FROZEN_NOT_RUN", "cases": 9, "api_requests": 0}))


def run():
    frozen = read(OUT / (STEM + "_freeze.json"))
    if verify_files(ROOT, frozen["source_sha256"]):
        raise ValueError("scaling candidate/source changed")
    if (OUT / (STEM + "_predictions.json")).exists():
        raise ValueError("completed scaling predictions cannot be replaced")
    source = load("benchmarks/vnext/binding_fixture_reference_v2.py", "scale_source")
    adapter = load("benchmarks/vnext/binding_fixture_adapter_v2.py", "scale_adapter")
    spec = read(ROOT / SPEC)
    values, rows = list(inputs(spec)), []
    if [{"case_id": value["case_id"], "input_sha256": digest(value["input"])} for value in values] != frozen["input_hashes"]:
        raise ValueError("scaling fixture input mismatch")
    for value in values:
        executed = source.execute_fixture(value["input"])
        projected = source.candidate_input(executed)
        started = time.perf_counter()
        envelope, snapshots, registry, methods, query = adapter.make_context(projected)
        normalized = normalize_envelope(envelope)
        index = TemporalQueryIndex(normalized.ledger, snapshots, registry, methods)
        built = time.perf_counter()
        evidence = index.evaluate(query)
        queried = time.perf_counter()
        try:
            receipt = make_temporal_certificate(envelope, snapshots, registry, methods, evidence)
            valid = validate_temporal_certificate(receipt, envelope, snapshots, registry, methods, evidence)
        except ValueError:
            receipt, valid = None, False
        checked = time.perf_counter()
        rows.append({"case_id": value["case_id"], "event_count": len(normalized.ledger.events), "template": value["template"],
            "source_sha256": digest(projected), "evidence": asdict(evidence), "receipt": asdict(receipt) if receipt else None,
            "receipt_valid": valid, "source_records": len(index.records.observations),
            "timing_ms": {"source_normalize_index": round((built - started) * 1000, 6),
                "indexed_query": round((queried - built) * 1000, 6),
                "independent_receipt_make_and_validate": round((checked - queried) * 1000, 6),
                "total": round((checked - started) * 1000, 6)}, "candidate_code_changed": False})
        print(json.dumps({"completed": len(rows), "total": 9, "case_id": value["case_id"], "receipt_valid": valid,
            "timing_ms": rows[-1]["timing_ms"]}), flush=True)
    ids = [row["case_id"] for row in rows]
    write_new(OUT / (STEM + "_predictions.json"), rows)
    seal = prediction_seal(rows, frozen["case_ids"], architecture_commit=frozen["architecture_commit"],
        configuration_sha256=frozen["configuration_sha256"])
    write_new(OUT / (STEM + "_prediction_seal.json"), seal)
    scored = []
    for value, row in zip(values, rows):
        reference = source.reference_query(source.execute_fixture(value["input"]))
        evidence = row["evidence"]
        expected_count = (value["event_count"] - 4) // 2 if value["template"] == "mutation-count" else 0
        actual_count = sum(len(binding["occurrences"]) for binding in evidence["bindings"])
        components = []
        if row["event_count"] != value["event_count"]:
            components.append("SOURCE_BINDING")
        if evidence["value"] != reference["truth"]:
            components.append("TEMPORAL_BINDING")
        if [binding["entity"]["value"] for binding in evidence["bindings"]] != [binding["record_id"] for binding in reference["bindings"]]:
            components.append("ENTITY_BINDING")
        if actual_count != expected_count:
            components.append("EVIDENCE_COMPLETENESS")
        if not row["receipt_valid"]:
            components.append("CERTIFICATE")
        scored.append({"case_id": row["case_id"], "event_count": row["event_count"], "template": row["template"],
            "candidate_truth": evidence["value"], "reference": reference, "candidate_bindings": len(evidence["bindings"]),
            "candidate_method_calls": actual_count, "expected_method_calls": expected_count,
            "searched_event_count": len(evidence["searched_event_ids"]), "source_records": row["source_records"],
            "candidate_set_complete": evidence["candidate_set_complete"], "timing_ms": row["timing_ms"],
            "receipt_valid": row["receipt_valid"], "failure_components": components,
            "core_certificate": "NOT_GENERATED"})
    report = {"scope": spec["scope"], "freeze_sha256": file_digest(OUT / (STEM + "_freeze.json")),
        "predictions_sha256": file_digest(OUT / (STEM + "_predictions.json")), "prediction_seal": seal,
        "case_count": 9, "correct_full_rows": sum(not case["failure_components"] for case in scored),
        "primitive_receipts_valid": sum(case["receipt_valid"] for case in scored), "cases": scored,
        "limitations": ["single-run timings, not population throughput or general complexity proof",
            "index build/query and full independent receipt replay reported separately",
            "explicit executable fixture authority only; no native NL or whole-Core correctness measured",
            "immutable v4 still uses cached alias scans and full call/result source replay; optimization belongs to a new version"],
        "api_requests": 0, "provider_schema_transport": "NOT_APPLICABLE", "whole_core_evaluation": "NOT_RUN", "blind_gold_opened": False}
    write_new(OUT / (STEM + "_results.json"), report)
    print(json.dumps({"status": "FULL_SCALING_REPORT_AND_CASE_AUDIT_COMPLETE", "correct_full_rows": report["correct_full_rows"], "cases": 9, "api_requests": 0}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "run"))
    (freeze if parser.parse_args().action == "freeze" else run)()
