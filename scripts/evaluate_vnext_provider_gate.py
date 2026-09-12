"""Versioned, resumable sequential B.AI microtask gate; no blind input or keys saved."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import time

from guardian_truth.llm_client import ChatClient, ClientConfig
from guardian_truth.runtime import provider_config
from guardian_truth.settings import load_env_file
from guardian_truth.vnext.integrity import digest, file_digest, verify_files, write_new
from guardian_truth.vnext.semantic import ChatSemanticBackend


ROOT = Path(__file__).resolve().parents[1]
TASKS = (
    ("actor", "The user deleted Q-17. The assistant only requested a check.",
        ("user", "assistant", "UNKNOWN"), "user"),
    ("kind", "I will restore Q-17 tomorrow.",
        ("INTENT", "ACTION_COMPLETED", "STATE", "UNKNOWN"), "INTENT"),
    ("completion", 'The tool result is {"status":"accepted"}. No completion result exists.',
        ("CONFIRMED", "UNCONFIRMED", "UNKNOWN"), "UNCONFIRMED"),
    ("causality", 'Restore timed out. Later GET returned {"exists":true}. Is restore causality proved?',
        ("PROVED", "UNPROVED", "UNKNOWN"), "UNPROVED"),
)


def schema_for(values):
    return {"type": "object", "additionalProperties": False, "required": ["value"],
        "properties": {"value": {"type": "string", "enum": list(values)}}}


def percentile(values, fraction):
    ordered = sorted(values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * fraction
    low, high = int(position), min(int(position) + 1, len(ordered) - 1)
    return round(ordered[low] + (ordered[high] - ordered[low]) * (position - low), 3)


def summarize(rows):
    transport = sum(row["classification"] != "TRANSPORT_ERROR" for row in rows)
    schema = sum(row["classification"] in {"SEMANTIC_CORRECT", "SEMANTIC_WRONG"} for row in rows)
    correct = sum(row["classification"] == "SEMANTIC_CORRECT" for row in rows)
    return {"status": "PASSED" if len(rows) == 12 and transport == schema == 12 and correct >= 11 else "NOT_ADMITTED",
        "scheduled": 12, "attempted": len(rows), "transport_success": transport,
        "schema_valid": schema, "semantic_correct": correct,
        "semantic_wrong": schema - correct, "transport_errors": len(rows) - transport,
        "schema_errors": transport - schema,
        "transport_rate": transport / len(rows) if rows else None,
        "schema_rate_given_transport": schema / transport if transport else None,
        "semantic_accuracy_given_valid": correct / schema if schema else None,
        "latency_ms_p50": percentile([row["telemetry"]["latency_ms"] for row in rows], .5),
        "latency_ms_p95": percentile([row["telemetry"]["latency_ms"] for row in rows], .95),
        "token_usage": {key: sum(row["telemetry"]["usage"].get(key, 0) for row in rows)
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")},
        "cost": "NOT_AUDITED"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"v[1-9][0-9]*", args.version):
        raise ValueError("a versioned experiment is required")
    output = ROOT / "outputs/vnext"
    prefix = "provider_gate_" + args.version
    freeze_path, report_path = output / (prefix + "_freeze.json"), output / (prefix + ".json")
    if report_path.exists():
        raise FileExistsError("finished gate is immutable; use a new version")
    source_names = ("scripts/evaluate_vnext_provider_gate.py", "src/guardian_truth/vnext/semantic.py",
        "src/guardian_truth/llm_client.py", "src/guardian_truth/runtime.py", "src/guardian_truth/settings.py")
    definition = {"tasks": TASKS, "repeats": 3, "schemas": [schema_for(task[2]) for task in TASKS],
        "provider": "bai", "model": "qwen3.8-flash", "timeout_seconds": 180,
        "max_output_tokens": 2048, "max_retries": 0, "response_format_mode": "none",
        "interval_seconds": 10, "temperature": 0,
        "admission": "12/12 transport and schema; >=11/12 semantic correctness",
        "failure_policy": "stop immediately on first transport failure; no hidden retry",
        "scope": "controlled development reliability microtasks; not stage or blind performance"}
    if freeze_path.exists():
        freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
        if freeze["definition_sha256"] != digest(definition) or verify_files(ROOT, freeze["source_sha256"]):
            raise ValueError("resumed gate implementation/configuration changed")
    else:
        freeze = {"definition": definition, "definition_sha256": digest(definition),
            "source_sha256": {name: file_digest(ROOT / name) for name in source_names},
            "implementation_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                capture_output=True, text=True, check=True).stdout.strip(),
            "frozen_utc": datetime.now(timezone.utc).isoformat()}
        write_new(freeze_path, freeze)
    load_env_file(args.env_file)
    config = provider_config(ClientConfig(timeout_seconds=180, max_output_tokens=2048,
        max_retries=0, response_format_mode="none"), "bai", model="qwen3.8-flash")
    records = []
    backend = ChatSemanticBackend(ChatClient(config), interval_seconds=10, checkpoint=records.append)
    rows = []
    for index in range(12):
        name, text, values, expected = TASKS[index % len(TASKS)]
        path = output / f"{prefix}_attempt_{index + 1:02d}.json"
        if path.exists():
            row = json.loads(path.read_text(encoding="utf-8"))
            if row["configuration_sha256"] != digest(freeze) or row["attempt"] != index + 1:
                raise ValueError("resumed attempt belongs to another gate")
            rows.append(row)
            if row["classification"] == "TRANSPORT_ERROR":
                break
            # Resuming never starts immediately after the previous request.
            backend.last_start = time.monotonic()
            continue
        proposal = backend.propose("gate_" + name, {"text": text,
            "instructions": "Interpret this narrow semantic field only. Intent is not completion; user is not assistant; accepted is not completed; a later state is not causal evidence."},
            schema_for(values))
        classification = "TRANSPORT_ERROR" if proposal.transport_status != "SUCCESS" else (
            "SCHEMA_ERROR" if proposal.schema_status != "VALID" else (
                "SEMANTIC_CORRECT" if proposal.value["value"] == expected else "SEMANTIC_WRONG"))
        row = {"attempt": index + 1, "task": name, "repeat": index // 4 + 1,
            "classification": classification, "prediction": proposal.value,
            "telemetry": records[-1], "configuration_sha256": digest(freeze)}
        write_new(path, row)
        rows.append(row)
        print(json.dumps({"attempt": index + 1, "task": name, "classification": classification}), flush=True)
        if classification == "TRANSPORT_ERROR":
            break
    report = {"schema_version": "guardian-vnext-provider-gate-v1", **summarize(rows),
        "freeze_sha256": file_digest(freeze_path), "implementation_commit": freeze["implementation_commit"],
        "created_utc": datetime.now(timezone.utc).isoformat(), "blind_cases_read": 0, "rows": rows}
    write_new(report_path, report)
    print(json.dumps({key: value for key, value in report.items() if key != "rows"}), flush=True)
    return 0 if report["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
