"""Fixed C2 vs ten-pass Claim Graph, with immutable per-request artifacts."""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import time

from guardian_truth.cycle2.claims import (claim_messages, load_claim_arm_contract,
    model_claim_proposal, response_spans)
from guardian_truth.llm_client import ChatClient, ClientConfig
from guardian_truth.runtime import provider_config
from guardian_truth.settings import load_env_file
from guardian_truth.vnext.claims import build_claim_graph
from guardian_truth.vnext.experiment import PersistedSemanticBackend, ProviderPause, quota_pause_reason
from guardian_truth.vnext.integrity import digest, file_digest, prediction_seal, verify_files, write_new
from guardian_truth.vnext.latency import percentile
from guardian_truth.vnext.semantic import ChatSemanticBackend
from scripts.vnext_claim_scoring import RULES, summarize


ROOT = Path(__file__).resolve().parents[1]
FIELD_TASKS = {"claim_disposition": ("disposition",), "claim_kind": ("kind",),
    "claim_actor": ("actor",), "claim_predicate": ("predicate",),
    "claim_object_entities": ("object", "entity_refs"), "claim_modality_polarity": ("modality", "polarity"),
    "claim_time": ("time_anchor",), "claim_source": ("source_refs",), "claim_relations": ("relations",),
    "claim_explicit_causality": ("explicit_causality",)}


def c2_prediction(case, client, delegate, contract, prefix, freeze, live_records):
    output = ROOT / "outputs/vnext"
    request_path, result_path = output / (prefix + "_c2_request.json"), output / (prefix + "_c2_result.json")
    messages, schema, _ = claim_messages(case, "C2", contract)
    request = {"messages": messages, "schema": schema, "prompt_sha256": digest(messages),
        "schema_sha256": digest(schema), "configuration_sha256": digest(freeze)}
    if result_path.exists():
        if digest(json.loads(request_path.read_text(encoding="utf-8"))) != digest(request):
            raise ValueError("C2 cached request changed")
        artifact = json.loads(result_path.read_text(encoding="utf-8"))
        if artifact["request_sha256"] != digest(request):
            raise ValueError("C2 result request binding changed")
        return artifact["row"]
    pause = quota_pause_reason(live_records)
    if pause:
        raise ProviderPause(pause)
    if request_path.exists():
        if digest(json.loads(request_path.read_text(encoding="utf-8"))) != digest(request):
            raise ValueError("unfinished C2 request changed")
        row = {"case_id": case["case_id"], "arm": "C2", "transport_status": "ERROR",
            "schema_status": "NOT_EVALUATED", "claims": [], "coverage": [],
            "error_category": "abandoned_request_capture", "usage": {}, "latency_ms": 0,
            "served_model": None, "remote_outcome": "UNKNOWN_NO_AUTOMATIC_RETRY"}
    else:
        write_new(request_path, request)
        if delegate.last_start is not None:
            delay = 10 - (time.monotonic() - delegate.last_start)
            if delay > 0:
                time.sleep(delay)
        delegate.last_start = time.monotonic()
        row = model_claim_proposal(client, case, "C2", contract)
        live_records.append(row)
    write_new(result_path, {"request_sha256": digest(request), "row": row})
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--gate", type=Path, default=ROOT / "outputs/vnext/provider_gate_v1.json")
    args = parser.parse_args()
    if not re.fullmatch(r"v[1-9][0-9]*", args.version):
        raise ValueError("versioned stage required")
    prefix, output = "claim_graph_" + args.version, ROOT / "outputs/vnext"
    freeze_path = output / (prefix + "_freeze.json")
    result_path = output / (prefix + "_results.json")
    if result_path.exists():
        raise FileExistsError("finished joined experiment cannot be rerun")
    benchmark_path = ROOT / "benchmarks/vnext/claim_graph_v1.json"
    contract_path = ROOT / "contracts/cycle2_claim_arms_v1.json"
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    if digest(benchmark["cases"]) != benchmark["cases_sha256"]:
        raise ValueError("claim benchmark hash mismatch")
    inputs = [{"case_id": case["case_id"], "response": case["input"]["response"]} for case in benchmark["cases"]]
    ids = [case["case_id"] for case in inputs]
    gate = json.loads(args.gate.read_text(encoding="utf-8"))
    if gate["status"] != "PASSED":
        raise ValueError("provider development gate not admitted")
    definition = {"provider": "bai", "model": "qwen3.8-flash", "temperature": 0,
        "timeout_seconds": 180, "max_output_tokens": 2048, "max_retries": 0,
        "response_format_mode": "none", "interval_seconds": 10, "arms": ["C2", "vnext"],
        "scoring": RULES, "C2_commit": "0199bf933d40f2b1fdc16a97cd3637ad9c97ced2",
        "C2_semantic_contract_sha256": file_digest(contract_path), "field_task_mapping": FIELD_TASKS,
        "random_seed": 260913, "scope": "controlled development extension; response only; not blind"}
    source_names = [path.relative_to(ROOT).as_posix() for path in (ROOT / "src/guardian_truth").rglob("*.py")]
    source_names += ["scripts/evaluate_vnext_claims.py", "scripts/vnext_claim_scoring.py",
                    "contracts/cycle2_claim_arms_v1.json"]
    if freeze_path.exists():
        freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
        if (freeze["definition_sha256"] != digest(definition) or freeze["case_ids"] != ids
                or freeze["benchmark_sha256"] != file_digest(benchmark_path)
                or verify_files(ROOT, freeze["source_sha256"])):
            raise ValueError("resumed claim experiment changed")
    else:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
            capture_output=True, text=True, check=True).stdout.strip()
        freeze = {"schema_version": "guardian-vnext-claim-stage-freeze-v1", "architecture_commit": commit,
            "definition": definition, "definition_sha256": digest(definition), "case_ids": ids,
            "case_inputs_sha256": digest(inputs), "benchmark_sha256": file_digest(benchmark_path),
            "source_sha256": {name: file_digest(ROOT / name) for name in sorted(source_names)},
            "gate_sha256": file_digest(args.gate), "frozen_utc": datetime.now(timezone.utc).isoformat(),
            "prompt_hash_policy": "all exact prompts/schemas persisted before transport"}
        write_new(freeze_path, freeze)
    load_env_file(args.env_file)
    config = provider_config(ClientConfig(timeout_seconds=180, max_output_tokens=2048,
        max_retries=0, response_format_mode="none"), "bai", model="qwen3.8-flash")
    client = ChatClient(config)
    live_records = []
    delegate = ChatSemanticBackend(client, interval_seconds=10, checkpoint=live_records.append)
    contract = load_claim_arm_contract(contract_path)
    rows = []
    try:
        for index, case in enumerate(inputs):
            stem = f"{prefix}_case_{index:03d}"
            path = output / (stem + ".json")
            if path.exists():
                row = json.loads(path.read_text(encoding="utf-8"))
                if row["case_id"] != case["case_id"] or row["configuration_sha256"] != digest(freeze):
                    raise ValueError("cached claim case changed")
            else:
                c2 = c2_prediction(case, client, delegate, contract, stem, freeze, live_records)
                backend = PersistedSemanticBackend(delegate, output, stem,
                    configuration_sha256=digest(freeze), live_records=live_records)
                graph = build_claim_graph(case["response"], backend)
                raw_path = output / (stem + "_request_000_result.json")
                raw = json.loads(raw_path.read_text(encoding="utf-8"))["proposal"] if raw_path.exists() else None
                disposition = json.loads(raw["payload_json"]) if raw and raw["schema_status"] == "VALID" else {"spans": []}
                lookup = {item["span_id"]: item["disposition"] for item in disposition["spans"]}
                inventory = response_spans(case["response"])
                failed = sorted({field for task, _ in graph.failures for field in FIELD_TASKS[task]})
                if raw and raw["schema_status"] != "VALID":
                    failed = sorted(set(failed) | {"disposition"})
                row = {"case_id": case["case_id"], "configuration_sha256": digest(freeze),
                    "prediction": {"vnext": asdict(graph), "C2": c2, "inventory": inventory,
                        "vnext_failed_fields": failed, "vnext_dispositions": [
                            {"start": span["start"], "end": span["end"], "disposition": lookup.get(span["span_id"], "UNKNOWN_SEMANTICS")}
                            for span in inventory]}, "vnext_request_telemetry": backend.records}
                write_new(path, row)
                print(json.dumps({"completed": index + 1, "total": len(inputs), "case_id": case["case_id"],
                    "C2_schema": c2["schema_status"], "vnext_failures": len(graph.failures)}), flush=True)
            rows.append(row)
    except ProviderPause as error:
        print(json.dumps({"status": "PROVIDER_PAUSED", "reason": str(error), "completed": len(rows),
            "total": len(inputs), "same_experiment_resumable": True}), flush=True)
        return 2
    predictions_path = output / (prefix + "_predictions.json")
    seal_path = output / (prefix + "_prediction_seal.json")
    seal = prediction_seal(rows, ids, architecture_commit=freeze["architecture_commit"], configuration_sha256=digest(freeze))
    if not predictions_path.exists():
        write_new(predictions_path, rows)
    if digest(json.loads(predictions_path.read_text(encoding="utf-8"))) != seal["prediction_sha256"]:
        raise ValueError("claim prediction seal mismatch")
    if not seal_path.exists():
        write_new(seal_path, seal)
    if json.loads(seal_path.read_text(encoding="utf-8")) != seal:
        raise ValueError("stored claim prediction seal mismatch")
    report = {"experiment": prefix, "architecture_commit": freeze["architecture_commit"],
        "freeze_sha256": file_digest(freeze_path), "predictions_sha256": file_digest(predictions_path),
        "prediction_seal_sha256": file_digest(seal_path), **summarize(benchmark["cases"], rows)}
    for arm in ("C2", "vnext"):
        telemetry = [row["prediction"]["C2"] for row in rows] if arm == "C2" else [
            item for row in rows for item in row["vnext_request_telemetry"]]
        report.setdefault("provider", {})[arm] = {"attempts": len(telemetry),
            "transport_success": sum(item["transport_status"] == "SUCCESS" for item in telemetry),
            "schema_valid": sum(item["schema_status"] == "VALID" for item in telemetry),
            "latency_ms_p50": percentile([item["latency_ms"] for item in telemetry], .5),
            "latency_ms_p95": percentile([item["latency_ms"] for item in telemetry], .95),
            "token_usage": {key: sum(item["usage"].get(key, 0) for item in telemetry) for key in ("prompt_tokens", "completion_tokens", "total_tokens")},
            "cost": "NOT_AUDITED"}
    for audit in report["failure_taxonomy"]:
        row = next(row for row in rows if row["case_id"] == audit["case_id"])
        all_telemetry = [row["prediction"]["C2"], *row["vnext_request_telemetry"]]
        if any(item["transport_status"] != "SUCCESS" for item in all_telemetry):
            audit["components"].append("TRANSPORT")
        if any(item["transport_status"] == "SUCCESS" and item["schema_status"] != "VALID" for item in all_telemetry):
            audit["components"].append("SCHEMA")
    write_new(result_path, report)
    write_new(output / (prefix + "_failure_audit.json"), {"experiment": prefix,
        "source_report_sha256": file_digest(result_path), "cases": report["failure_taxonomy"]})
    print(json.dumps({key: report[key] for key in ("case_count", "span_detection", "admission", "provider")}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
