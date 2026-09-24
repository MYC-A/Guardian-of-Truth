"""Source-bound diagnostic facts for the next Guardian comparison.

No result here is a policy verdict. Absence of a literal from the prompt is
not evidence that the agent was forbidden to derive it. These facts identify
precise opportunities for a typed policy/claim witness and preserve UNKNOWN.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from guardian_truth.parsing import parse_catalog, parse_events  # noqa: E402

FAILURE_STATUS = {"failed", "failure", "error", "declined", "denied", "rejected"}
RESULT_STATUS = {"completed", "success", "succeeded", "recorded", "approved", "granted"}
CLAIM_HINT = re.compile(
    r"(не могу|невозможно|нет (?:возможности|способа)|переда[юём]|"
    r"уже|успешно|выполнен|заверш[её]н|оформлен|зарегистрирован|"
    r"cannot|can't|impossible|not possible|no way|transferr?ing|"
    r"completed|processed|done|successful|already)", re.IGNORECASE)
OPAQUE_FIELD = re.compile(r"(?:^|_)(?:id|zip|postal|account|booking|reservation|case)(?:_|$)",
                          re.IGNORECASE)
GENERIC_SCALAR = {"", "true", "false", "null", "none", "yes", "no", "0", "1"}


def scalar_paths(value: Any, prefix: str = ""):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from scalar_paths(item, f"{prefix}.{key}" if prefix else key)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from scalar_paths(item, f"{prefix}[{index}]")
    elif value is not None and not isinstance(value, bool):
        yield prefix, value


def leaf(path: str) -> str:
    return re.sub(r"\[\d+\]", "", path).rsplit(".", 1)[-1]


def exact_literal(text: str, value: Any) -> bool:
    """Literal token equality; an email substring is not an exact ZIP source."""
    needle = str(value)
    if not needle or needle.lower() in GENERIC_SCALAR:
        return False
    # A sentence-final period is punctuation; a period followed by a word
    # continues a decimal, address or dotted identifier.
    return bool(re.search(r"(?<![\w@.-])" + re.escape(needle) +
                          r"(?![\w@-]|\.[\w])", text))


def result_outcome(value: Any) -> str:
    if not isinstance(value, dict):
        return "UNKNOWN"
    if value.get("success") is False or value.get("ok") is False:
        return "FAILED"
    if value.get("success") is True or value.get("ok") is True:
        return "SUCCEEDED"
    for key in ("status", "result", "outcome", "authorization_status", "audit_status"):
        item = value.get(key)
        if isinstance(item, str):
            token = item.strip().lower()
            if token in FAILURE_STATUS:
                return "FAILED"
            if token in RESULT_STATUS:
                return "SUCCEEDED"
    return "UNKNOWN"


def canonical_args(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def entity_anchors(value: Any) -> dict[str, Any]:
    """Only explicit identifier fields can join two events to one entity."""
    return {leaf(path): item for path, item in scalar_paths(value)
            if OPAQUE_FIELD.search(leaf(path)) and item is not None}


def same_entity(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """At least one shared anchor, and no conflicting shared anchor."""
    shared = left.keys() & right.keys()
    return bool(shared) and all(left[key] == right[key] for key in shared)


def local_record(case: dict[str, str]) -> dict:
    prompt, response = case["prompt"], case["response"]
    prompt_events = parse_events(prompt, "prompt")
    response_events = parse_events(response, "response")
    users = [(i, e) for i, e in enumerate(prompt_events)
             if e.role == "user" and e.kind == "text"]
    results = [(i, e) for i, e in enumerate(prompt_events) if e.kind == "result"]
    calls = [(i, e) for i, e in enumerate(prompt_events) if e.kind == "call"]
    targets = [(i, e) for i, e in enumerate(response_events)
               if e.role == "assistant" and e.kind == "call"]
    catalog = parse_catalog(prompt_events, prompt)
    observations = []
    for index, event in results:
        if event.json_valid:
            anchors = entity_anchors(event.value)
            observations.extend({"event": index, "tool": event.name,
                                 "path": path, "value": value,
                                 "anchors": anchors,
                                 "source": [event.source.start, event.source.end]}
                                for path, value in scalar_paths(event.value))
    arguments = []
    for target_index, target in targets:
        if not target.json_valid or not isinstance(target.value, dict):
            arguments.append({"target_event": target_index, "tool": target.name,
                              "status": "UNKNOWN_MALFORMED_CALL", "args": []})
            continue
        fields = []
        target_anchors = entity_anchors(target.value)
        for path, value in scalar_paths(target.value):
            key = leaf(path)
            user_sources = [i for i, user in users if exact_literal(user.text, value)]
            exact_field = [o for o in observations
                           if o["value"] == value and leaf(o["path"]) == key
                           and (not target_anchors or
                                same_entity(target_anchors, o["anchors"]))]
            other_field = [o for o in observations
                           if o["value"] == value and leaf(o["path"]) != key]
            if user_sources or exact_field:
                state = "SOURCE_FOUND"
            else:
                state = "UNKNOWN_NO_EXACT_SOURCE"
            fields.append({"path": path, "value": value, "status": state,
                           "opaque_field": bool(OPAQUE_FIELD.search(key)),
                           "user_events": user_sources,
                           "same_field_observations": exact_field[:5],
                           "other_field_observations": other_field[:5]})
        arguments.append({"target_event": target_index, "tool": target.name,
                          "status": "PARSED", "args": fields})
    attempted = []
    for call_index, call in calls:
        if call.role != "assistant":
            continue
        next_tool_event = next(((index, event) for index, event in
                                enumerate(prompt_events) if index > call_index
                                and event.kind in {"call", "result"}), None)
        if next_tool_event is None or next_tool_event[1].kind != "result" \
                or next_tool_event[1].name != call.name:
            continue
        result_index, matched = next_tool_event
        attempted.append({"tool": call.name, "args": canonical_args(call.value),
                          "call_event": call_index,
                          "result_event": result_index,
                          "outcome": result_outcome(matched.value) if matched.json_valid else "UNKNOWN"})
    repeated_failed = []
    for target_index, target in targets:
        args = canonical_args(target.value)
        same_calls = [prior for prior in attempted
                      if args is not None and prior["args"] == args
                      and prior["tool"] == target.name]
        if same_calls and same_calls[-1]["outcome"] == "FAILED":
            prior = same_calls[-1]
            repeated_failed.append({"target_event": target_index, "tool": target.name,
                                    "prior_call_event": prior["call_event"],
                                    "prior_result_event": prior["result_event"],
                                    "status": "EXACT_FAILED_REPLAY"})
    text_events = [(i, e) for i, e in enumerate(response_events)
                   if e.role == "assistant" and e.kind == "text"]
    claim_hints = [{"event": i, "text": e.text[:280],
                    "source": [e.source.start, e.source.end]}
                   for i, e in text_events if CLAIM_HINT.search(e.text)]
    return {"catalog_complete": catalog.complete, "catalog_issues": catalog.issues,
            "catalog_tools": sorted(catalog.tools), "arguments": arguments,
            "repeated_failed_calls": repeated_failed,
            "claim_hints": claim_hints,
            "n_history_results": len(results), "n_target_calls": len(targets)}
