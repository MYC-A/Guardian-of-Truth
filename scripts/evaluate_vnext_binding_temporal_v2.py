"""Frozen typed binding/temporal stage; source projection only, no API or blind gold."""

import argparse
from collections import Counter
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
SPEC = ROOT / "benchmarks/vnext/binding_temporal_v2.spec.json"
STEM = "binding_temporal_v2"


def load(relative, name):
    module_spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def head():
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def percentile(values, fraction):
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    return round(ordered[lower] + (ordered[min(lower + 1, len(ordered) - 1)] - ordered[lower]) * (position - lower), 6)


def freeze():
    if subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip() != "experiment/guardian-vnext-from-0199bf9":
        raise ValueError("independent vNext branch required")
    spec_freeze = read(OUT / (STEM + "_spec_freeze.json"))
    if verify_files(ROOT, spec_freeze["source_sha256"]):
        raise ValueError("source/reference specification changed")
    # Exact runnable Python dependencies, not credential/env files or unrelated
    # results. Archive text is evidence of the frozen source bytes only.
    paths = sorted(path.relative_to(ROOT).as_posix() for path in (ROOT / "src/guardian_truth").rglob("*.py"))
    paths += ["benchmarks/vnext/binding_fixture_reference_v2.py", "benchmarks/vnext/binding_fixture_adapter_v2.py",
        "scripts/evaluate_vnext_binding_temporal_v2.py", "tests/test_vnext_temporal_queries_v4.py"]
    for relative in paths:
        subprocess.run(["git", "ls-files", "--error-unmatch", relative], cwd=ROOT, capture_output=True, check=True)
    if subprocess.run(["git", "diff", "--quiet", "HEAD", "--", *paths], cwd=ROOT).returncode:
        raise ValueError("commit exact candidate sources before freezing")
    source = {relative: file_digest(ROOT / relative) for relative in paths}
    config = {"scope": "CONTROLLED_TYPED_QUERY_STAGE_NOT_NATIVE_FRONTEND_OR_BLIND_E2E",
        "api_requests": 0, "provider": None, "model": None, "semantic_frontend": "EXPLICIT_TYPED_FIXTURE_INPUT_NOT_LLM",
        "canonical_truth": ["TRUE", "FALSE", "BOTH", "UNKNOWN"], "binary_adapter": "NOT_APPLICABLE",
        "query_limit": "full supplied prefix; all compatible source bindings and results; no top-k",
        "certificate_scope": "typed source temporal primitive only; not whole-Core safety",
        "fix_boundary": "complete report and per-case audit before a next-version repair"}
    write_new(OUT / (STEM + "_source_archive.json"), {"scope": "EXACT_EXECUTABLE_SOURCE_BYTES_NOT_CANDIDATE_RESULTS",
        "architecture_commit": head(), "files": {relative: (ROOT / relative).read_bytes().decode("utf-8") for relative in paths}, "source_sha256": source})
    artifact = {"schema_version": "guardian-binding-candidate-freeze-v2", "architecture_commit": head(),
        "spec_freeze_sha256": file_digest(OUT / (STEM + "_spec_freeze.json")), "spec_sha256": file_digest(SPEC),
        "case_ids": spec_freeze["case_ids"], "source_sha256": source, "configuration": config,
        "configuration_sha256": digest(config), "blind_gold_opened": False}
    write_new(OUT / (STEM + "_freeze.json"), artifact)
    print(json.dumps({"status": "CANDIDATE_FROZEN_NOT_EVALUATED", "sources": len(source), "api_requests": 0}))


def run():
    frozen = read(OUT / (STEM + "_freeze.json"))
    if verify_files(ROOT, frozen["source_sha256"]) or file_digest(SPEC) != frozen["spec_sha256"]:
        raise ValueError("frozen candidate/source inputs changed")
    if any((OUT / (STEM + suffix)).exists() for suffix in ("_predictions.json", "_prediction_seal.json", "_results.json")):
        raise ValueError("completed experiment artifacts cannot be replaced or rerun")
    spec = read(SPEC)
    reference = load("benchmarks/vnext/binding_fixture_reference_v2.py", "binding_source")
    adapter = load("benchmarks/vnext/binding_fixture_adapter_v2.py", "binding_application_adapter")
    rows = []
    for case in spec["cases"]:
        # No annotation, family, ID or internal reference knowledge enters the
        # candidate. Source execution creates trace data, not candidate facts.
        source = reference.candidate_input(reference.execute_fixture(case["input"]))
        started = time.perf_counter()
        envelope, snapshots, registry, methods, query = adapter.make_context(source)
        normalized = normalize_envelope(envelope)
        index = TemporalQueryIndex(normalized.ledger, snapshots, registry, methods)
        evidence = index.evaluate(query)
        try:
            receipt = make_temporal_certificate(envelope, snapshots, registry, methods, evidence)
            valid = validate_temporal_certificate(receipt, envelope, snapshots, registry, methods, evidence)
        except ValueError:
            # A checker rejection is retained as a certificate failure, never
            # silently repaired, dropped or substituted with safe binary zero.
            receipt, valid = None, False
        rows.append({"case_id": case["id"], "input_sha256": digest(source), "evidence": asdict(evidence),
            "certificate": asdict(receipt) if receipt is not None else None, "certificate_valid": valid,
            "runtime_ms": round((time.perf_counter() - started) * 1000, 6),
            "source_event_count": len(normalized.ledger.events), "source_record_count": len(index.records.observations),
            "framing_complete": normalized.framing_complete, "source_reasons": [reason.value for reason in normalized.reasons]})
    ids = [row["case_id"] for row in rows]
    if ids != frozen["case_ids"]:
        raise ValueError("full exactly-once candidate inventory required")
    expected_inputs = read(OUT / (STEM + "_spec_freeze.json"))["candidate_input_hashes"]
    if [{"case_id": row["case_id"], "input_sha256": row["input_sha256"]} for row in rows] != expected_inputs:
        raise ValueError("candidate input projection differs from preimplementation source freeze")
    write_new(OUT / (STEM + "_predictions.json"), rows)
    seal = prediction_seal(rows, ids, architecture_commit=frozen["architecture_commit"], configuration_sha256=frozen["configuration_sha256"])
    write_new(OUT / (STEM + "_prediction_seal.json"), seal)
    # Scoring and independent reference-annotation join occurs only now, after
    # all 34 predictions are persisted and sealed. Controlled dev, NOT blind.
    scored, taxonomy = [], Counter()
    for case, row in zip(spec["cases"], rows):
        gold = reference.reference_query(reference.execute_fixture(case["input"]))
        observed = row["evidence"]
        expected_ids = sorted(item["record_id"] for item in gold["bindings"])
        observed_ids = sorted(item["entity"]["value"] for item in observed["bindings"])
        causes = []
        if observed_ids != expected_ids:
            causes.append("ENTITY_BINDING")
        if observed["value"] != gold["truth"]:
            causes.append("CAUSAL_REASONING" if case["input"]["query"]["kind"] == "CAUSE_OF_METHOD" else "TEMPORAL_BINDING")
        if observed["candidate_set_complete"] != gold["candidate_set_complete"]:
            causes.append("EVIDENCE_COMPLETENESS")
        if not row["certificate_valid"]:
            causes.append("CERTIFICATE")
        taxonomy.update(causes)
        scored.append({"case_id": case["id"], "family": case["family"], "kind": case["input"]["query"]["kind"],
            "gold": gold, "candidate_truth": observed["value"], "candidate_ids": observed_ids,
            "truth_correct": observed["value"] == gold["truth"], "binding_correct": observed_ids == expected_ids,
            "completeness_correct": observed["candidate_set_complete"] == gold["candidate_set_complete"],
            "certificate_valid": row["certificate_valid"], "failure_components": causes,
            "unknown_preserved": gold["truth"] == "UNKNOWN" and observed["value"] == "UNKNOWN",
            "unresolved_reasons": observed["reasons"]})
    ambiguous = [case for case in scored if len(case["gold"]["bindings"]) > 1]
    causal = [case for case in scored if case["kind"] == "CAUSE_OF_METHOD"]
    causal_positive = [case for case in causal if case["candidate_truth"] == "TRUE"]
    definite = [row for row in rows if row["evidence"]["value"] in {"TRUE", "FALSE"}]
    runtimes = [row["runtime_ms"] for row in rows]
    metrics = {"truth_correct": sum(case["truth_correct"] for case in scored),
        "binding_correct": sum(case["binding_correct"] for case in scored), "case_count": len(rows),
        "truth_distribution": dict(Counter(row["evidence"]["value"] for row in rows)),
        "ambiguous_cases": len(ambiguous), "ambiguity_preserved": sum(case["binding_correct"] for case in ambiguous),
        "false_forced_binding": sum(len(case["candidate_ids"]) == 1 and len(case["gold"]["bindings"]) != 1 for case in scored),
        "completeness_correct": sum(case["completeness_correct"] for case in scored),
        "causal_cases": len(causal), "positive_causal_proofs": len(causal_positive),
        "false_or_unsupported_causal_support": sum(case["gold"]["truth"] != "TRUE" for case in causal_positive),
        "source_scoped_causal_precision": sum(case["gold"]["truth"] == "TRUE" for case in causal_positive) / len(causal_positive) if causal_positive else None,
        "typed_receipts_valid": sum(row["certificate_valid"] for row in rows),
        "definitive_primitive_receipts_valid": sum(row["certificate_valid"] for row in definite), "definitive_primitive_count": len(definite),
        "core_certificate_validation": None, "whole_core_resolution": "NOT_RUN",
        "runtime_ms_p50": percentile(runtimes, .5), "runtime_ms_p95": percentile(runtimes, .95),
        "api_requests": 0, "tokens": 0, "provider_transport": "NOT_APPLICABLE", "provider_schema": "NOT_APPLICABLE",
        "provider_cost": "NOT_APPLICABLE_NO_API"}
    report = {"schema_version": "guardian-binding-temporal-stage-results-v2", "scope": frozen["configuration"]["scope"],
        "architecture_commit": frozen["architecture_commit"], "freeze_sha256": file_digest(OUT / (STEM + "_freeze.json")),
        "predictions_sha256": file_digest(OUT / (STEM + "_predictions.json")), "seal": seal,
        "metrics": metrics, "failure_taxonomy": dict(taxonomy), "cases": scored,
        "unresolved_reason_distribution": dict(Counter(reason for case in scored for reason in case["unresolved_reasons"])),
        "native_frontend_evaluation": "NOT_RUN", "blind_gold_opened": False,
        "interpretation": "typed source-scoped stage isolation, not native extraction, whole-Core safety, production gain or blind performance"}
    write_new(OUT / (STEM + "_results.json"), report)
    print(json.dumps({"scope": report["scope"], "metrics": metrics, "failure_taxonomy": report["failure_taxonomy"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "run"))
    (freeze if parser.parse_args().action == "freeze" else run)()
