"""Durable serial stages: one inference, at most one identical transport retry.

No gold is opened here. Interrupted requests with missing results are captured
as unknown, never sent again. Exclusive stage locks prevent concurrent replay
from misclassifying a live request as abandoned. Stale locks need explicit
process verification/removal; neither file age nor observation timeout suffices.
"""

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import time

from guardian_truth.llm_client import ChatClientError
from guardian_truth.parsing import decode_json
from .goal_v3_isolation_frontend_v2 import grounding_payload_v2, prompt_messages_v2, proposal_issues_v2
from .goal_v3_isolation_stage_gates_v2 import experiment_budget_v2
from .integrity import digest, prediction_seal, write_new


CONFIG = {"provider": "groq", "model": "qwen/qwen3.8-27b",
    "base_url": "https://api.groq.com/openai/v1", "api_key_env": "GROQ_API_KEY",
    "temperature": 0, "max_output_tokens": 2048, "timeout_seconds": 180,
    "response_format_mode": "auto", "reasoning_effort": None,
    "client_retries": 0, "transport_retries_per_case": 1,
    "retry_categories": ["timeout", "rate_limit", "server", "connection"],
    "retry_same_payload_only": True, "retry_backoff_seconds": 2,
    "concurrency": 1, "interval_seconds": 30, "semantic_calls_per_case": 1,
    "repair_rules": ["NONE", "EXACT_JSON_FENCE", "EXACT_FENCE"],
    "reported_token_ceilings": {"S1": 24000, "S2": 72000, "S3": 24000},
    "enforce_token_ceilings": False,
    "raw_completion_storage": "HASH_AND_SCHEMA_VALID_PROPOSAL_ONLY",
    "cache_behavior": "STABLE_PREFIX_NO_CACHE_GUARANTEE", "judge_calls": 0, "challenger_calls": 0}


def immutable(path, value):
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) != json.loads(json.dumps(value)):
            raise ValueError("immutable artifact mismatch")
    else:
        write_new(path, value)


def repair_v2(text):
    if not isinstance(text, str):
        return None, False, False, "NO_TEXT", ["JSON_INVALID"]
    value, valid = decode_json(text)
    raw = valid and isinstance(value, dict)
    code = "NONE"
    if not raw:
        stripped = text.strip()
        for prefix, name in (("```json\n", "EXACT_JSON_FENCE"), ("```\n", "EXACT_FENCE")):
            if stripped.startswith(prefix) and stripped.endswith("```"):
                value, valid = decode_json(stripped[len(prefix):-3].strip())
                code = name
                break
    issues = list(proposal_issues_v2(value)) if valid and isinstance(value, dict) else ["JSON_INVALID"]
    return value if not issues else None, bool(raw and not issues), not issues, code, issues


class StageRunnerV2:
    def __init__(self, output: Path, freeze: dict, client, *, sleeper=time.sleep):
        self.output, self.freeze, self.client, self.sleeper = output, freeze, client, sleeper
        self.config = freeze["configuration"]
        self.configuration_hash = digest(freeze)

    def path(self, name):
        return self.output / ("goal_v3_isolation_v2_" + name + ".json")

    def physical(self, case_id, ordinal, source, messages):
        stem = "case_" + case_id.replace(":", "_").lower() + f"_request_{ordinal:03d}"
        request_path, result_path = self.path(stem), self.path(stem + "_result")
        request = {"case_id": case_id, "ordinal": ordinal, "source_sha256": digest(source),
            "configuration_sha256": self.configuration_hash, "messages": messages,
            "payload_sha256": digest({"messages": messages, "configuration": self.config})}
        if result_path.exists():
            if not request_path.exists() or json.loads(request_path.read_text(encoding="utf-8")) != request:
                raise ValueError("physical request changed")
            result = json.loads(result_path.read_text(encoding="utf-8"))
            if result.get("request_sha256") != digest(request):
                raise ValueError("physical result lineage mismatch")
            return result
        telemetry = {"transport_status": "ERROR", "error_category": None, "retryable": False,
            "raw_schema_valid": False, "postrepair_schema_valid": False, "usage": {},
            "served_model": None, "latency_ms": 0, "repair_code": "NO_CAPTURE", "schema_issue_codes": []}
        proposal = None
        if request_path.exists():
            if json.loads(request_path.read_text(encoding="utf-8")) != request:
                raise ValueError("interrupted request changed")
            telemetry.update(error_category="abandoned_request_capture", remote_outcome="UNKNOWN_NO_AUTOMATIC_RETRY")
        else:
            write_new(request_path, request)
            started = time.monotonic()
            try:
                completion = self.client.complete(messages, schema=None, reasoning_effort=None)
                proposal, raw, repaired, code, issues = repair_v2(completion.content)
                telemetry.update(transport_status="SUCCESS", raw_schema_valid=raw,
                    postrepair_schema_valid=repaired, repair_code=code, schema_issue_codes=issues,
                    raw_completion_sha256=hashlib.sha256(completion.content.encode("utf-8")).hexdigest(),
                    usage={key: value for key, value in completion.usage.items()
                        if key in {"prompt_tokens", "completion_tokens", "total_tokens"} and type(value) is int},
                    served_model=completion.model)
            except ChatClientError as error:
                telemetry.update(error_category=error.category,
                    retryable=bool(error.retryable and error.category in self.config["retry_categories"]))
            telemetry["latency_ms"] = round((time.monotonic() - started) * 1000, 3)
        result = {"request_sha256": digest(request), "proposal": proposal, "telemetry": telemetry}
        write_new(result_path, result)
        return result

    def case(self, case_id, source):
        messages, records = prompt_messages_v2(source), []
        for ordinal in range(2):
            result = self.physical(case_id, ordinal, source, messages)
            records.append(result["telemetry"])
            if not result["telemetry"]["retryable"]:
                break
            if ordinal == 0:
                self.sleeper(self.config["retry_backoff_seconds"])
        proposal = result["proposal"]
        grounding = grounding_payload_v2(source, proposal) if proposal is not None else {
            "grounding": {"candidate": None, "summary_world_consistent": False, "diagnostics": ["NO_PROPOSAL"]},
            "certificate": None}
        row = {"case_id": case_id, "source_sha256": digest(source), "proposal": proposal,
            **grounding, "telemetry": result["telemetry"], "request_telemetry": records,
            "physical_requests": len(records)}
        immutable(self.path("case_" + case_id.replace(":", "_").lower()), row)
        return row

    def run(self, stage, inputs):
        ids = self.freeze["stages"][stage]
        self.output.mkdir(parents=True, exist_ok=True)
        lock = self.path(stage + "_run_lock")
        # Creation is exclusive; do not remove a lock we did not acquire.
        import os
        write_new(lock, {"pid": os.getpid(), "stage": stage, "configuration_sha256": self.configuration_hash})
        try:
            rows, physical = [], []
            for case_id in ids:
                row = self.case(case_id, inputs[case_id])
                rows.append(row)
                physical.extend(row["request_telemetry"])
                budget = experiment_budget_v2(physical, ceiling=self.config["reported_token_ceilings"][stage],
                    enforce_token_ceiling=self.config["enforce_token_ceilings"])
                if not budget.admit_next_request:
                    break
                if len(rows) < len(ids):
                    self.sleeper(self.config["interval_seconds"])
            attempted = [row["case_id"] for row in rows]
            predictions = self.path(stage + "_predictions")
            immutable(predictions, rows)
            seal = prediction_seal(rows, attempted, architecture_commit=self.freeze["architecture_commit"],
                configuration_sha256=self.configuration_hash)
            immutable(self.path(stage + "_prediction_seal"), seal)
            boundary = {"stage": stage, "requested_case_ids": ids, "attempted_case_ids": attempted,
                "not_run_case_ids": ids[len(rows):], "complete": len(rows) == len(ids),
                "budget": asdict(budget), "configuration_sha256": self.configuration_hash,
                "prediction_sha256": digest(rows), "seal_sha256": digest(seal)}
            immutable(self.path(stage + "_boundary"), boundary)
            return boundary
        finally:
            lock.unlink()  # Only this process's newly created stage lock.
