"""Durable per-request semantic artifacts; no credentials or raw server errors."""

from dataclasses import asdict
import json
from pathlib import Path

from .integrity import digest, write_new
from .semantic import Proposal, SYSTEM


class ProviderPause(RuntimeError):
    """A safe terminal process outcome, not a semantic false negative."""


def quota_pause_reason(records: list[dict]) -> str | None:
    if len(records) >= 2 and all(row.get("error_category") == "rate_limit" for row in records[-2:]):
        return "TWO_CONSECUTIVE_RATE_LIMITS"
    if len(records) >= 3 and all(row["transport_status"] != "SUCCESS" for row in records[-3:]):
        return "THREE_CONSECUTIVE_TRANSPORT_ERRORS"
    if len(records) >= 16 and sum(row["transport_status"] == "SUCCESS" for row in records[-16:]) / 16 < .9:
        return "LAST_16_TRANSPORT_BELOW_90_PERCENT"
    return None


class PersistedSemanticBackend:
    """Replay persisted proposals, never retry a failed narrow request invisibly."""

    def __init__(self, delegate, directory: Path, prefix: str, *, configuration_sha256: str,
                 live_records: list[dict]):
        import re
        if not re.fullmatch(r"[a-z0-9_]+", prefix):
            raise ValueError("safe artifact prefix required")
        self.delegate, self.directory, self.prefix = delegate, directory, prefix
        self.configuration_sha256, self.live_records = configuration_sha256, live_records
        self.cursor = 0
        self.records = []

    def propose(self, task, payload, schema):
        index = self.cursor
        self.cursor += 1
        stem = f"{self.prefix}_request_{index:03d}"
        request_path, result_path = self.directory / (stem + ".json"), self.directory / (stem + "_result.json")
        messages = [{"role": "system", "content": SYSTEM}, {"role": "user",
            "content": "TASK: " + task + "\nDATA_JSON: " + json.dumps(payload, ensure_ascii=False,
                sort_keys=True, separators=(",", ":"), allow_nan=False)
            + "\nOUTPUT_JSON_SCHEMA: " + json.dumps(schema, ensure_ascii=False,
                sort_keys=True, separators=(",", ":"), allow_nan=False)}]
        request = {"configuration_sha256": self.configuration_sha256, "ordinal": index,
            "task": task, "payload": payload, "schema": schema,
            "input_sha256": digest(payload), "schema_sha256": digest(schema),
            "prompt_sha256": digest(messages)}
        if result_path.exists():
            if not request_path.exists() or digest(json.loads(request_path.read_text(encoding="utf-8"))) != digest(request):
                raise ValueError("persisted proposal source/configuration changed")
            artifact = json.loads(result_path.read_text(encoding="utf-8"))
            if artifact["request_sha256"] != digest(request):
                raise ValueError("persisted proposal request hash mismatch")
            self.records.append(artifact["telemetry"])
            return Proposal(**artifact["proposal"])
        pause = quota_pause_reason(self.live_records)
        if pause:
            raise ProviderPause(pause)
        if request_path.exists():
            if digest(json.loads(request_path.read_text(encoding="utf-8"))) != digest(request):
                raise ValueError("unfinished request source/configuration changed")
            # A terminated process lost capture after a request was admitted.
            # The remote outcome is unknown. Do not send the same request again.
            proposal = Proposal(None, "ERROR", "NOT_EVALUATED", "abandoned_request_capture")
            telemetry = {"task": task, "transport_status": "ERROR", "schema_status": "NOT_EVALUATED",
                "error_category": proposal.error_category, "usage": {}, "latency_ms": 0,
                "input_sha256": request["input_sha256"], "schema_sha256": request["schema_sha256"],
                "prompt_sha256": request["prompt_sha256"], "served_model": None,
                "remote_outcome": "UNKNOWN_NO_AUTOMATIC_RETRY"}
        else:
            write_new(request_path, request)
            proposal = self.delegate.propose(task, payload, schema)
            telemetry = self.live_records[-1]
            for key in ("input_sha256", "schema_sha256", "prompt_sha256"):
                if telemetry[key] != request[key]:
                    raise ValueError("delegate request differs from pre-request freeze")
        write_new(result_path, {"request_sha256": digest(request), "proposal": asdict(proposal), "telemetry": telemetry})
        self.records.append(telemetry)
        return proposal
