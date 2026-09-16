"""Semantic backend with deterministic raw-JSON extraction.

qwen3.8-flash occasionally wraps its JSON object in markdown fences or a
short prose preamble even when asked not to. This backend extracts the FIRST
balanced JSON object from the completion content before decoding - a pure
transport-level, content-preserving normalization (the registered format
repair of spec 28/33). It never re-asks, never edits the JSON itself, and
records every extraction as a receipt note. One semantic attempt per input
remains the rule.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Callable

from ..integrity import canonical, digest
from ..semantic import Proposal, SYSTEM, schema_valid
from guardian_truth.parsing import decode_json


def extract_first_json_object(content: str) -> str | None:
    """First balanced top-level {...} object, ignoring fences/prose."""
    if not content:
        return None
    start = content.find("{")
    while start >= 0:
        depth, in_string, escaped = 0, False, False
        for index in range(start, len(content)):
            char = content[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    candidate = content[start:index + 1]
                    value, valid = decode_json(candidate)
                    if valid:
                        return candidate
                    break
        start = content.find("{", start + 1)
    return None


class JsonExtractBackend:
    """SemanticBackend protocol over a ChatClient with fence/prose stripping."""

    def __init__(self, client, *, interval_seconds: float = 10,
                 reasoning_effort: str | None = "low",
                 checkpoint: Callable[[dict], None] | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.client = client
        self.interval_seconds = interval_seconds
        self.reasoning_effort = reasoning_effort
        self.checkpoint = checkpoint
        self.clock, self.sleep = clock, sleep
        self.last_start = None
        self.lock = threading.Lock()
        self.extraction_notes: list[str] = []

    def propose(self, task: str, payload: dict, schema: dict) -> Proposal:
        messages = [{"role": "system", "content": SYSTEM},
                    {"role": "user", "content": "TASK: " + task + "\nDATA_JSON: "
                     + canonical(payload).decode("utf-8")
                     + "\nOUTPUT_JSON_SCHEMA: " + canonical(schema).decode("utf-8")}]
        record = {"task": task, "input_sha256": digest(payload), "prompt_sha256": digest(messages),
                  "schema_sha256": digest(schema), "served_model": None, "usage": {}, "latency_ms": 0,
                  "transport_status": "ERROR", "schema_status": "NOT_EVALUATED", "error_category": None}
        with self.lock:
            if self.last_start is not None:
                delay = self.interval_seconds - (self.clock() - self.last_start)
                if delay > 0:
                    self.sleep(delay)
            started = self.last_start = self.clock()
        try:
            completion = self.client.complete(messages, schema=schema,
                                              reasoning_effort=self.reasoning_effort)
            record["transport_status"] = "SUCCESS"
            record["served_model"] = completion.model
            record["usage"] = {key: value for key, value in
                               (("prompt_tokens", completion.usage.get("prompt_tokens")),
                                ("completion_tokens", completion.usage.get("completion_tokens")),
                                ("total_tokens", completion.usage.get("total_tokens")))
                               if type(value) is int and value >= 0}
            content = completion.content
            extracted = extract_first_json_object(content)
            if extracted is not None and extracted != content.strip():
                self.extraction_notes.append(f"{task}:stripped-surrounding-text")
            value, valid_json = decode_json(extracted if extracted is not None else content)
            valid = valid_json and schema_valid(value, schema)
            record["schema_status"] = "VALID" if valid else "INVALID"
            result = Proposal(canonical(value).decode("utf-8") if valid else None,
                              "SUCCESS", record["schema_status"])
        except Exception as error:  # ChatClientError only in practice
            record["error_category"] = getattr(error, "category", "transport")
            result = Proposal(None, "ERROR", "NOT_EVALUATED", record["error_category"])
        record["latency_ms"] = round(max(0, self.clock() - started) * 1000, 3)
        if self.checkpoint:
            self.checkpoint(record)
        return result
