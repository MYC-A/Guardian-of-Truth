"""Gold-free adapter from official competition rows to frozen E2E input.

The adapter is deliberately syntactic.  It preserves the original prompt for
normalization, extracts only marker-delimited/source-quoted fields, converts
the declared textual argument grammar to JSON-schema-shaped data, and leaves
all unavailable trust metadata absent.  Tool names/descriptions never become
effect semantics here.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from guardian_truth.parsing import FieldSpec, Source, parse_catalog, parse_events

from ..integrity import digest
from .e2e_types_v1 import E2ECaseInput


ADAPTER_VERSION = "guardian-real-competition-adapter-v1"
_POLICY = re.compile(r"<policy>\s*(.*?)\s*</policy>", re.IGNORECASE | re.DOTALL)
_TOOL_HEADER = re.compile(r"^-\s+([\w.-]+)\s+[—–-]\s*(.*)$")


@dataclass(frozen=True)
class CompetitionInput:
    case: E2ECaseInput
    policy_source: Source | None
    request_source: Source | None
    tool_declarations: tuple[dict, ...]
    adapter_version: str = ADAPTER_VERSION


def _object_schema(fields: list[FieldSpec]) -> dict:
    properties = {field.name: _field_schema(field) for field in fields}
    required = [field.name for field in fields if field.required]
    schema = {"type": "object", "properties": properties, "additionalProperties": False}
    if required:
        schema["required"] = required
    return schema


def _field_schema(field: FieldSpec) -> dict:
    schema = {"type": field.kind}
    if field.enum:
        schema["enum"] = list(field.enum)
    if field.kind == "array":
        schema["items"] = _object_schema(field.children) if field.children else {}
    elif field.kind == "object":
        schema.update(_object_schema(field.children))
    return schema


def _policy(system_event, prompt: str) -> tuple[str, Source | None]:
    matches = list(_POLICY.finditer(system_event.text))
    if matches:
        match = matches[-1]
        start = system_event.source.start + match.start(1)
        end = system_event.source.start + match.end(1)
        return prompt[start:end], Source("prompt", start, end)
    raw = system_event.text
    end = raw.find("[AVAILABLE TOOLS]")
    value = raw[:end if end >= 0 else len(raw)].strip()
    if not value:
        return "", None
    relative = raw.find(value)
    start = system_event.source.start + relative
    return value, Source("prompt", start, start + len(value))


def _description(raw: str, name: str) -> str:
    first = raw.splitlines()[0] if raw.splitlines() else ""
    match = _TOOL_HEADER.match(first)
    if not match or match.group(1) != name:
        return ""
    return match.group(2).strip()


def _source_dict(source: Source, prompt: str) -> dict:
    return {"document": source.document, "start": source.start,
            "end": source.end, "quote": prompt[source.start:source.end]}


def _argument_declarations(fields: list[FieldSpec], prompt: str,
                           prefix: tuple[str, ...] = ()) -> list[dict]:
    declarations = []
    for field in fields:
        path = prefix + (field.name,)
        declarations.append({"path": list(path), "kind": field.kind,
                             "required": field.required, "enum": list(field.enum),
                             "source": _source_dict(field.source, prompt)})
        declarations.extend(_argument_declarations(field.children, prompt, path))
    return declarations


def adapt_competition_input(record: dict) -> CompetitionInput:
    """Accept only the official inference view: id, prompt and response."""
    if not isinstance(record, dict) or set(record) != {"id", "prompt", "response"}:
        raise ValueError("competition adapter accepts exactly id, prompt, response")
    case_id, prompt, response = record["id"], record["prompt"], record["response"]
    if not isinstance(case_id, str) or not case_id.strip():
        raise ValueError("nonempty string id required")
    if not isinstance(prompt, str) or not isinstance(response, str):
        raise ValueError("prompt and response must be strings")

    events = parse_events(prompt, "prompt")
    systems = [event for event in events if event.role == "system" and event.kind == "text"]
    if len(systems) != 1:
        raise ValueError("competition prompt must contain exactly one SYSTEM block")
    users = [event for event in events if event.role == "user" and event.kind == "text"]
    if not users:
        raise ValueError("competition prompt must contain a USER request")
    system_policy, policy_source = _policy(systems[0], prompt)
    request = users[-1]

    catalog = parse_catalog(events, prompt)
    if catalog.source is None or not catalog.complete:
        raise ValueError("competition prompt tool catalog is missing or incomplete")
    tool_schemas, tool_metadata, declarations = [], [], []
    for name, spec in sorted(catalog.tools.items()):
        raw = prompt[spec.source.start:spec.source.end]
        parameters = _object_schema(spec.fields)
        schema_hash = digest(parameters)
        source_hash = digest(raw)
        description = _description(raw, name)
        source = _source_dict(spec.source, prompt)
        description_source = None
        if description:
            relative = raw.find(description)
            start = spec.source.start + relative
            description_source = _source_dict(Source("prompt", start, start + len(description)), prompt)
        tool_schemas.append({"name": name, "description": description,
                             "parameters": parameters, "source": source})
        # These values identify this exact source declaration; they do not
        # assert an external provider/version or any effect semantics.
        tool_metadata.append({"name": name, "provider": "competition-prompt",
                              "version": source_hash, "schema_sha256": schema_hash})
        declarations.append({"name": name, "description": description,
                             "schema_sha256": schema_hash, "source": source,
                             "description_source": description_source,
                             "arguments": _argument_declarations(spec.fields, prompt),
                             "schema_understood": spec.schema_understood})

    case = E2ECaseInput(
        case_id=case_id,
        family="competition_public",
        system_policy=system_policy,
        user_request=request.text,
        history=(),
        target_response=response,
        tool_metadata=tuple(tool_metadata),
        tool_schemas=tuple(tool_schemas),
        t1_contracts=(),
        state_contract=None,
        history_complete=False,
        completeness_basis=None,
        authoritative_policy_readings=(),
        authoritative_goal_readings=(),
        authoritative_policy_behaviors=(),
        authoritative_goal_behaviors=(),
        raw_prompt=prompt,
    )
    return CompetitionInput(case, policy_source, request.source, tuple(declarations))
