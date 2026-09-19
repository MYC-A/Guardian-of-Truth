#!/usr/bin/env python3
"""Prepare gold-free Granite function-call rows from competition-format CSV.

This adapter is deliberately a probabilistic-model input adapter.  A parsed
catalog gives Granite context but never establishes that tools outside it do
not exist.  Every output decision is accompanied by a source-preserving trace.
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from guardian_truth.parsing import parse_catalog, parse_events
from guardian_truth.types import FieldSpec, Source, ToolSpec


ADAPTER_VERSION = "granite-function-call-preprocess-v1"
MAX_CSV_FIELD_CHARS = 16 * 1024 * 1024


@dataclass(frozen=True)
class PreparedRow:
    row: dict[str, str]
    trace: dict[str, Any]


def _source(source: Source, document: str) -> dict[str, Any]:
    return {"document": source.document, "start": source.start, "end": source.end,
            "quote": document[source.start:source.end]}


def _field_schema(field: FieldSpec) -> dict[str, Any]:
    """Represent only the textual FieldSpec; do not invent object closure."""
    schema: dict[str, Any] = {"type": field.kind}
    if field.enum:
        schema["enum"] = list(field.enum)
    if field.kind == "object":
        schema["properties"] = {child.name: _field_schema(child) for child in field.children}
        required = [child.name for child in field.children if child.required]
        if required:
            schema["required"] = required
    elif field.kind == "array" and field.children:
        items: dict[str, Any] = {
            "type": "object",
            "properties": {child.name: _field_schema(child) for child in field.children},
        }
        required = [child.name for child in field.children if child.required]
        if required:
            items["required"] = required
        schema["items"] = items
    return schema


def _field_trace(field: FieldSpec, prompt: str) -> dict[str, Any]:
    return {"name": field.name, "kind": field.kind, "required": field.required,
            "enum": list(field.enum), "source": _source(field.source, prompt),
            "children": [_field_trace(child, prompt) for child in field.children]}


def _tool(tool: ToolSpec) -> dict[str, Any]:
    # Granite's existing runner expects parameters as a field-name mapping.
    return {
        "name": tool.name,
        "description": "",
        "parameters": {field.name: _field_schema(field) for field in tool.fields},
    }


def _unavailable(case_id: str, reason: str, diagnostics: list[str], trace: dict[str, Any]) -> PreparedRow:
    trace.update({"status": "unavailable", "reason": reason, "diagnostics": diagnostics})
    return PreparedRow(
        {"id": case_id, "prompt": "", "response": "", "tools": "",
         "adapter_status": "unavailable", "adapter_reason": reason},
        trace,
    )


def prepare_record(record: dict[str, str]) -> PreparedRow:
    """Convert one ``id,prompt,response`` row without reading labels or gold data."""
    required = {"id", "prompt", "response"}
    if not required.issubset(record):
        raise ValueError("input record must contain id, prompt, response")
    case_id, prompt, response = (record[key] for key in ("id", "prompt", "response"))
    if not isinstance(case_id, str) or not case_id.strip() or not isinstance(prompt, str) or not isinstance(response, str):
        raise ValueError("id must be nonempty and prompt/response must be strings")

    prompt_events = parse_events(prompt, "prompt")
    response_events = parse_events(response, "response")
    users = [event for event in prompt_events
             if event.role == "user" and event.kind == "text" and event.text.strip()]
    calls = [event for event in response_events if event.role == "assistant" and event.kind == "call"]
    trace: dict[str, Any] = {
        "adapter_version": ADAPTER_VERSION,
        "id": case_id,
        "input": {"prompt_chars": len(prompt), "response_chars": len(response)},
        "parser_issues": [],
        "selected_user": _source(users[-1].source, prompt) if users else None,
        "target_calls": [
            {"name": call.name, "json_valid": call.json_valid,
             "source": _source(call.source, response)} for call in calls
        ],
    }
    if not users:
        return _unavailable(case_id, "missing_relevant_user_message", [], trace)
    if not calls:
        return _unavailable(case_id, "missing_target_assistant_tool_call", [], trace)
    if any(not call.name or not call.json_valid or not isinstance(call.value, dict) for call in calls):
        return _unavailable(case_id, "unparsed_or_nonobject_target_call", [], trace)

    catalog = parse_catalog(prompt_events, prompt)
    trace["parser_issues"] = list(catalog.issues)
    trace["catalog"] = {
        "complete": catalog.complete,
        "source": _source(catalog.source, prompt) if catalog.source else None,
        "tool_names": sorted(catalog.tools),
    }
    if catalog.source is None:
        return _unavailable(case_id, "missing_or_ambiguous_catalog", list(catalog.issues), trace)
    if not catalog.complete:
        return _unavailable(case_id, "incomplete_or_truncated_catalog", list(catalog.issues), trace)
    if not catalog.tools:
        return _unavailable(case_id, "empty_catalog", list(catalog.issues), trace)
    bad_schemas = sorted(name for name, tool in catalog.tools.items() if not tool.schema_understood)
    if bad_schemas:
        return _unavailable(case_id, "ununderstood_declared_schema", bad_schemas, trace)

    tools = [_tool(catalog.tools[name]) for name in sorted(catalog.tools)]
    serialized_calls = [{"name": call.name, "arguments": call.value} for call in calls]
    model_response: Any = serialized_calls[0] if len(serialized_calls) == 1 else serialized_calls
    trace.update({
        "status": "ready",
        "probabilistic_only": True,
        "tool_universe_closed": False,
        "available_tools": tools,
        "tool_declarations": [
            {"name": tool.name, "source": _source(tool.source, prompt),
             "schema_understood": tool.schema_understood,
             "fields": [_field_trace(field, prompt) for field in tool.fields]}
            for tool in (catalog.tools[name] for name in sorted(catalog.tools))
        ],
    })
    return PreparedRow(
        {"id": case_id, "prompt": users[-1].text, "response": json.dumps(model_response, ensure_ascii=False),
         "tools": json.dumps(tools, ensure_ascii=False), "adapter_status": "ready", "adapter_reason": ""},
        trace,
    )


def preprocess_csv(input_path: Path, output_path: Path, trace_path: Path) -> int:
    # Competition prompts routinely exceed the csv module's 128 KiB default.
    # Keep a finite ceiling so a malformed input cannot request unbounded RAM.
    csv.field_size_limit(MAX_CSV_FIELD_CHARS)
    with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = {"id", "prompt", "response"} - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"input CSV misses columns: {', '.join(sorted(missing))}")
        records = list(reader)
    seen: set[str] = set()
    prepared: list[PreparedRow] = []
    for line_number, record in enumerate(records, start=2):
        if record["id"] in seen:
            raise ValueError(f"duplicate id {record['id']!r} at line {line_number}")
        seen.add(record["id"])
        prepared.append(prepare_record(record))
    if output_path.exists() or trace_path.exists():
        raise ValueError("refusing to overwrite output or trace")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["id", "prompt", "response", "tools", "adapter_status", "adapter_reason"])
        writer.writeheader()
        writer.writerows(item.row for item in prepared)
    with trace_path.open("x", encoding="utf-8") as handle:
        for item in prepared:
            handle.write(json.dumps(item.trace, ensure_ascii=False) + "\n")
    return sum(item.row["adapter_status"] == "ready" for item in prepared)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--trace", required=True, type=Path)
    args = parser.parse_args()
    ready = preprocess_csv(args.input, args.output, args.trace)
    print(f"prepared {ready} ready rows; CSV={args.output}; trace={args.trace}")


if __name__ == "__main__":
    main()
