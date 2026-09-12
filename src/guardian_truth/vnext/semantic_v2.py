"""Explicit v2 transport adds value-free schema diagnostics; v1 remains frozen."""

from dataclasses import asdict
import threading
import time

from guardian_truth.llm_client import ChatClientError
from .integrity import canonical, digest
from .schema_diagnostics import diagnose_completion
from .semantic import Proposal, SYSTEM


class DiagnosticSemanticBackend:
    def __init__(self, client, *, interval_seconds=10, checkpoint=None,
                 clock=time.monotonic, sleep=time.sleep):
        self.client, self.interval_seconds, self.checkpoint = client, interval_seconds, checkpoint
        self.clock, self.sleep, self.last_start, self.lock = clock, sleep, None, threading.Lock()

    def propose(self, task, payload, schema):
        messages = [{"role": "system", "content": SYSTEM}, {"role": "user",
            "content": "TASK: " + task + "\nDATA_JSON: " + canonical(payload).decode("utf-8")
                + "\nOUTPUT_JSON_SCHEMA: " + canonical(schema).decode("utf-8")}]
        record = {"backend_version": "diagnostic-semantic-v2", "task": task,
            "input_sha256": digest(payload), "prompt_sha256": digest(messages), "schema_sha256": digest(schema),
            "served_model": None, "usage": {}, "latency_ms": 0, "transport_status": "ERROR",
            "schema_status": "NOT_EVALUATED", "schema_issues": [], "error_category": None}
        with self.lock:
            if self.last_start is not None:
                delay = self.interval_seconds - (self.clock() - self.last_start)
                if delay > 0:
                    self.sleep(delay)
            started = self.last_start = self.clock()
            try:
                completion = self.client.complete(messages, schema=schema, reasoning_effort="low")
                value, issues = diagnose_completion(completion.content, schema)
                record.update(transport_status="SUCCESS", schema_status="INVALID" if issues else "VALID",
                    schema_issues=[asdict(issue) for issue in issues], served_model=completion.model,
                    usage={key: item for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                        if type(item := completion.usage.get(key)) is int and item >= 0})
                result = Proposal(None if issues else canonical(value).decode("utf-8"),
                    "SUCCESS", record["schema_status"])
            except ChatClientError as error:
                record["error_category"] = error.category
                result = Proposal(None, "ERROR", "NOT_EVALUATED", error.category)
            record["latency_ms"] = round(max(0, self.clock() - started) * 1000, 3)
            if self.checkpoint:
                self.checkpoint(record)
            return result
