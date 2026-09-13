"""Durable staged Goal-only experiment: one compact semantic call per case.

No Policy parser, candidate/gold join during inference, LLM judge, challenger,
semantic retry or raw server-error storage. A remote outcome lost after a
persisted request is UNKNOWN_NO_AUTOMATIC_RETRY on resume.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess
import time

from guardian_truth.llm_client import ChatClient, ChatClientError, ClientConfig
from guardian_truth.runtime import provider_config
from guardian_truth.settings import load_env_file
from guardian_truth.vnext.goal_v3_isolation_frontend_v1 import (
    PROMPT_SHA256, SCHEMA, SCHEMA_SHA256, ground_candidate, prompt_messages,
)
from guardian_truth.vnext.goal_v3_isolation_repair_v1 import repair_goal_json_v1
from guardian_truth.vnext.integrity import digest, file_digest, prediction_seal, verify_files, write_new


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/vnext"
PREFIX = "goal_v3_isolation_v1"
SOURCES = (
    "scripts/evaluate_goal_v3_isolation_v1.py",
    "src/guardian_truth/vnext/goal_v3_isolation_frontend_v1.py",
    "src/guardian_truth/vnext/goal_v3_isolation_repair_v1.py",
    "src/guardian_truth/vnext/goal_v3_isolation_scoring_v1.py",
    "src/guardian_truth/vnext/goal_alignment_v3.py",
    "src/guardian_truth/vnext/goal_alignment_certificate_v3.py",
    "src/guardian_truth/vnext/integrity.py",
    "src/guardian_truth/vnext/schema_diagnostics.py",
    "src/guardian_truth/vnext/latency.py",
    "src/guardian_truth/llm_client.py",
    "src/guardian_truth/runtime.py",
    "src/guardian_truth/settings.py",
    "docs/vnext/GOAL_V3_ISOLATION_PROTOCOL_V1.md",
)
CONFIG = {"provider": "bai", "model": "qwen3.8-flash", "base_url": "https://api.b.ai/v1",
    "temperature": 0, "max_output_tokens": 512, "timeout_seconds": 180,
    "response_format_mode": "none", "client_retries": 0, "transport_retries_per_case": 1,
    "retry_categories": ["timeout", "rate_limit", "server", "connection"],
    "retry_same_payload_only": True, "concurrency": 1, "interval_seconds": 10,
    "retry_backoff_seconds": 2,
    "semantic_calls_per_case": 1, "challenger_calls": 0, "judge_calls": 0,
    "repair_rules": ["NONE", "EXACT_JSON_FENCE", "EXACT_FENCE", "UNIQUE_OBJECT_EXTRACTION"],
    "raw_completion_storage": "SHA256_AND_PARSED_VALID_OBJECT_ONLY",
    "binary_adapter": "NONE_GOAL_ONLY", "random_seed": 260913}


def path(name):
    return OUT / f"{PREFIX}_{name}.json"


def read(name):
    return json.loads(path(name).read_text(encoding="utf-8"))


def write_immutable(target, value):
    """Complete interrupted artifact writes without replacing sealed content."""
    if target.exists():
        if json.loads(target.read_text(encoding="utf-8")) != value:
            raise ValueError(f"immutable Goal artifact changed: {target.name}")
    else:
        write_new(target, value)


def stage_key(stage):
    return {"S1": "S1_smoke", "S2": "S2_remaining_core", "S3": "S3_stress"}[stage]


def freeze():
    if path("inference_freeze").exists():
        raise FileExistsError("Goal-only inference freeze already exists")
    bench = read("benchmark_freeze")
    if (bench["inputs_sha256"] != file_digest(path("inputs"))
            or bench["gold_sha256"] != file_digest(path("gold"))
            or verify_files(ROOT, bench["source_sha256"])):
        raise ValueError("frozen Goal-only benchmark source/gold mismatch")
    if subprocess.run(["git", "diff", "--quiet", "HEAD", "--", *SOURCES], cwd=ROOT).returncode:
        raise ValueError("commit exact candidate/runner/scorer/prompt before inference freeze")
    if any(subprocess.run(["git", "ls-files", "--error-unmatch", name], cwd=ROOT,
                          capture_output=True).returncode for name in SOURCES):
        raise ValueError("all inference sources must be tracked")
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
        capture_output=True, text=True, check=True).stdout.strip()
    write_new(path("inference_freeze"), {"schema_version": "guardian-goal-v3-isolation-inference-freeze-v1",
        "architecture_commit": commit, "implementation_origin_commit": "48b84e3875b960d43956576735d543e8c4e5917b",
        "implemented_from_spec": "COMPACT_USER_GOAL_SEMANTIC_PROPOSAL_NOT_GENERAL_AUTHORITY_CERTIFICATE",
        "benchmark_freeze_sha256": file_digest(path("benchmark_freeze")),
        "inputs_sha256": file_digest(path("inputs")), "gold_sha256": file_digest(path("gold")),
        "case_ids": bench["case_ids"], "stages": bench["stages"],
        "source_sha256": {name: file_digest(ROOT / name) for name in SOURCES},
        "prompt_sha256": PROMPT_SHA256, "schema_sha256": SCHEMA_SHA256, "schema": SCHEMA,
        "configuration": CONFIG, "configuration_sha256": digest(CONFIG),
        "early_stop_rules": {"S1": "smoke_admission in frozen scorer", "S2": "core_admission in frozen scorer",
            "S3": "stress behavioral correctness >= 0.80"},
        "max_semantic_cases": 60, "max_physical_requests": 120,
        "experimental_llm_calls_before_freeze": 0,
        "score_only_after_stage_prediction_seal": True})


def verify_freeze():
    freeze_data, bench = read("inference_freeze"), read("benchmark_freeze")
    if (file_digest(path("benchmark_freeze")) != freeze_data["benchmark_freeze_sha256"]
            or file_digest(path("inputs")) != freeze_data["inputs_sha256"]
            or file_digest(path("gold")) != freeze_data["gold_sha256"]
            or verify_files(ROOT, freeze_data["source_sha256"])
            or verify_files(ROOT, bench["source_sha256"])
            or freeze_data["configuration"] != CONFIG or freeze_data["configuration_sha256"] != digest(CONFIG)
            or freeze_data["prompt_sha256"] != PROMPT_SHA256 or freeze_data["schema_sha256"] != SCHEMA_SHA256
            or freeze_data["schema"] != SCHEMA or freeze_data["case_ids"] != bench["case_ids"]
            or freeze_data["stages"] != bench["stages"]):
        raise ValueError("Goal-only inference freeze changed")
    return freeze_data, bench


def _request_artifact(case_id, ordinal, source, messages, config_hash):
    return {"case_id": case_id, "ordinal": ordinal, "configuration_sha256": config_hash,
        "source_sha256": digest(source), "messages": messages,
        "prompt_sha256": digest(messages), "schema_sha256": SCHEMA_SHA256,
        "provider": CONFIG["provider"], "model": CONFIG["model"]}


def _request_paths(case_id, ordinal):
    safe = case_id.replace(":", "_").lower()
    stem = f"{PREFIX}_case_{safe}_request_{ordinal:03d}"
    return path(stem[len(PREFIX) + 1:]), path(stem[len(PREFIX) + 1:] + "_result")


def physical_request(case_id, ordinal, source, messages, config_hash, client):
    request_path, result_path = _request_paths(case_id, ordinal)
    request = _request_artifact(case_id, ordinal, source, messages, config_hash)
    if result_path.exists():
        if not request_path.exists() or json.loads(request_path.read_text(encoding="utf-8")) != request:
            raise ValueError("cached physical Goal request differs from frozen source")
        cached = json.loads(result_path.read_text(encoding="utf-8"))
        if cached["request_sha256"] != digest(request):
            raise ValueError("cached physical Goal result/request link differs")
        return cached
    if request_path.exists():
        if json.loads(request_path.read_text(encoding="utf-8")) != request:
            raise ValueError("admitted Goal request changed after interrupted capture")
        telemetry = {"transport_status": "ERROR", "error_category": "abandoned_request_capture",
            "remote_outcome": "UNKNOWN_NO_AUTOMATIC_RETRY", "raw_schema_valid": False,
            "postrepair_schema_valid": False, "repair_code": "NO_CAPTURE", "schema_issue_codes": [],
            "latency_ms": 0, "usage": {}, "served_model": None, "retryable": False}
        result = {"request_sha256": digest(request), "proposal": None, "telemetry": telemetry}
        write_new(result_path, result)
        return result
    write_new(request_path, request)
    started = time.monotonic()
    try:
        completion = client.complete(messages, schema=None, reasoning_effort=None)
        repair = repair_goal_json_v1(completion.content)
        telemetry = {"transport_status": "SUCCESS", "error_category": None,
            "raw_completion_sha256": hashlib.sha256(completion.content.encode("utf-8")).hexdigest(),
            "raw_schema_valid": repair.raw_schema_valid,
            "postrepair_schema_valid": repair.postrepair_schema_valid,
            "repair_code": repair.repair_code, "schema_issue_codes": list(repair.schema_issue_codes),
            "latency_ms": round((time.monotonic() - started) * 1000, 3),
            "usage": {key: value for key, value in completion.usage.items()
                if key in {"prompt_tokens", "completion_tokens", "total_tokens"} and type(value) is int},
            "served_model": completion.model, "retryable": False}
        proposal = repair.value
    except ChatClientError as error:
        telemetry = {"transport_status": "ERROR", "error_category": error.category,
            "raw_schema_valid": False, "postrepair_schema_valid": False,
            "repair_code": "NOT_EVALUATED", "schema_issue_codes": [],
            "latency_ms": round((time.monotonic() - started) * 1000, 3),
            "usage": {}, "served_model": None,
            "retryable": bool(error.retryable and error.category in CONFIG["retry_categories"])}
        proposal = None
    result = {"request_sha256": digest(request), "proposal": proposal, "telemetry": telemetry}
    write_new(result_path, result)
    return result


def run_case(case_id, source, client, config_hash):
    messages = prompt_messages(source)
    attempts = []
    for ordinal in range(CONFIG["transport_retries_per_case"] + 1):
        result = physical_request(case_id, ordinal, source, messages, config_hash, client)
        attempts.append(result["telemetry"])
        if result["telemetry"]["transport_status"] == "SUCCESS" or not result["telemetry"]["retryable"]:
            break
        if ordinal < CONFIG["transport_retries_per_case"]:
            time.sleep(CONFIG["retry_backoff_seconds"] * (2 ** ordinal))
    proposal = result["proposal"]
    grounding = asdict(ground_candidate(source, proposal)) if proposal is not None else None
    return {"case_id": case_id, "source_sha256": digest(source), "proposal": proposal,
        "grounding": grounding, "telemetry": result["telemetry"],
        "request_telemetry": attempts, "physical_requests": len(attempts)}


def _stage_name(stage):
    return {"S1": "S1_smoke", "S2": "S2_core", "S3": "S3_stress"}[stage]


def _stage_ids(stage, benchmark):
    key = stage_key(stage)
    return benchmark["stages"][key]


def run_stage(stage, env_file):
    frozen, benchmark = verify_freeze()
    if stage == "S2" and not read("S1_smoke_results")["admission"]["admit_S2"]:
        raise ValueError("frozen S1 early-stop gate rejected S2")
    if stage == "S3" and not read("S2_core_results")["admission"]["admit_S3"]:
        raise ValueError("frozen S2 gate rejected S3")
    if env_file is None or not load_env_file(env_file):
        raise ValueError("explicit existing credential file required for admitted stage")
    config = provider_config(ClientConfig(timeout_seconds=CONFIG["timeout_seconds"],
        max_output_tokens=CONFIG["max_output_tokens"], max_retries=0,
        response_format_mode="none"), CONFIG["provider"], model=CONFIG["model"])
    if config.base_url != CONFIG["base_url"]:
        raise ValueError("provider endpoint differs from freeze")
    client = ChatClient(config)
    client.validate_configuration()  # local-only: no test ping/API call
    inputs = {row["case_id"]: row["source"] for row in read("inputs")}
    rows = []
    for case_id in _stage_ids(stage, benchmark):
        case_path = path("case_" + case_id.replace(":", "_").lower())
        if case_path.exists():
            row = json.loads(case_path.read_text(encoding="utf-8"))
            if row["case_id"] != case_id or row["source_sha256"] != digest(inputs[case_id]):
                raise ValueError("cached Goal case differs from frozen source")
            if any(not _request_paths(case_id, ordinal)[1].exists() for ordinal in range(row["physical_requests"])):
                raise ValueError("cached Goal case lacks a captured physical request result")
            if row != run_case(case_id, inputs[case_id], client, digest(frozen)):
                raise ValueError("cached Goal case differs from replayed physical requests")
        else:
            row = run_case(case_id, inputs[case_id], client, digest(frozen))
            write_new(case_path, row)
        rows.append(row)
        print(json.dumps({"stage": stage, "completed": len(rows), "total": len(_stage_ids(stage, benchmark)),
            "case_id": case_id, "transport": row["telemetry"]["transport_status"],
            "schema": row["telemetry"]["postrepair_schema_valid"]}), flush=True)
        if len(rows) < len(_stage_ids(stage, benchmark)):
            time.sleep(CONFIG["interval_seconds"])
    name = _stage_name(stage)
    write_immutable(path(name + "_predictions"), rows)
    write_immutable(path(name + "_prediction_seal"), prediction_seal(rows, _stage_ids(stage, benchmark),
        architecture_commit=frozen["architecture_commit"], configuration_sha256=digest(frozen)))


def score_stage(stage):
    frozen, benchmark = verify_freeze()
    name = _stage_name(stage)
    rows = read(name + "_predictions")
    ids = _stage_ids(stage, benchmark)
    seal = read(name + "_prediction_seal")
    if seal != prediction_seal(rows, ids, architecture_commit=frozen["architecture_commit"],
                               configuration_sha256=digest(frozen)):
        raise ValueError("Goal gold cannot be joined before a complete sealed stage")
    for prior in (("S1",) if stage == "S2" else ("S1", "S2") if stage == "S3" else ()):
        prior_name, prior_ids = _stage_name(prior), _stage_ids(prior, benchmark)
        prior_rows, prior_seal = read(prior_name + "_predictions"), read(prior_name + "_prediction_seal")
        if prior_seal != prediction_seal(prior_rows, prior_ids,
                architecture_commit=frozen["architecture_commit"], configuration_sha256=digest(frozen)):
            raise ValueError("earlier stage prediction seal changed")
    if file_digest(path("gold")) != frozen["gold_sha256"]:
        raise ValueError("frozen Goal gold changed")
    # Gold is opened only here, after this stage's exact prediction seal.
    gold = read("gold")
    from guardian_truth.vnext.goal_v3_isolation_scoring_v1 import (
        core_admission, smoke_admission, summarize_goal_v3_stage,
    )
    if stage == "S1":
        stage_rows, all_ids = rows, ids
    elif stage == "S2":
        stage_rows = read("S1_smoke_predictions") + rows
        all_ids = benchmark["stages"]["S1_smoke"] + ids
    else:
        stage_rows = read("S1_smoke_predictions") + read("S2_core_predictions") + rows
        all_ids = benchmark["stages"]["S1_smoke"] + benchmark["stages"]["S2_remaining_core"] + ids
    summary = summarize_goal_v3_stage(read("inputs"), gold, stage_rows,
        benchmark["case_inventory"], all_ids)
    stress_cases = [row for row in summary["failure_taxonomy"] if row["case_id"] in set(ids)]
    stress_accuracy = sum(row["behavioral_correct"] for row in stress_cases) / len(stress_cases) if stress_cases else None
    admission = smoke_admission(summary) if stage == "S1" else core_admission(summary) if stage == "S2" else {
        "stress_behavioral_accuracy": stress_accuracy,
        "stress_readiness_signal": stress_accuracy is not None and stress_accuracy >= .8,
        "verdict": "REJECT" if summary["certified_resolution_rate"] == 0 else "KEEP"}
    report = {"experiment": PREFIX, "stage": stage, "scope": "GOAL_ONLY_SEMANTIC_CANDIDATE_NOT_WHOLE_CORE",
        "implementation_commit": frozen["architecture_commit"],
        "prompt_sha256": frozen["prompt_sha256"], "schema_sha256": frozen["schema_sha256"],
        "benchmark_freeze_sha256": frozen["benchmark_freeze_sha256"],
        "inference_freeze_sha256": file_digest(path("inference_freeze")),
        "prediction_seal_sha256": file_digest(path(name + "_prediction_seal")),
        "summary": summary, "admission": admission,
        "not_run_case_ids": [case_id for case_id in frozen["case_ids"] if case_id not in set(all_ids)]}
    write_immutable(path(name + "_results"), report)
    write_immutable(path(name + "_failure_audit"), {"stage": stage,
        "source_report_sha256": file_digest(path(name + "_results")),
        "cases": summary["failure_taxonomy"]})
    print(json.dumps({"stage": stage, "attempted": summary["attempted_cases"],
        "behavioral_correct": summary["behavioral_correct"], "admission": admission}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("freeze", "run", "score"))
    parser.add_argument("--stage", choices=("S1", "S2", "S3"))
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args()
    if args.phase == "freeze":
        freeze()
    elif args.phase == "run":
        if not args.stage:
            parser.error("--stage required for run")
        run_stage(args.stage, args.env_file)
    else:
        if not args.stage:
            parser.error("--stage required for score")
        score_stage(args.stage)


if __name__ == "__main__":
    main()
