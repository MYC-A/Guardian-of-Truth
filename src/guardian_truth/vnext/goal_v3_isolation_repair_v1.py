"""Frozen value-preserving JSON extraction; never fixes semantic/schema fields."""

from dataclasses import dataclass

from guardian_truth.parsing import decode_json
from .goal_v3_isolation_frontend_v1 import SCHEMA
from .schema_diagnostics import schema_issues


@dataclass(frozen=True)
class RepairResultV1:
    value: dict | None
    raw_schema_valid: bool
    postrepair_schema_valid: bool
    repair_code: str
    schema_issue_codes: tuple[str, ...]


def _object_slices(text):
    starts, depth, quoted, escaped = [], 0, False, False
    for index, char in enumerate(text):
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
        elif char == "{":
            if depth == 0:
                starts.append(index)
            depth += 1
        elif char == "}":
            depth -= 1
            if depth < 0:
                return ()
            if depth == 0:
                starts.append(index + 1)
    if depth or quoted or len(starts) != 2:
        return ()
    return ((starts[0], starts[1]),)


def repair_goal_json_v1(text):
    """Accept a single exact JSON object, optionally fenced/surrounded by text.

    No missing key, enum, Boolean, value, or candidate meaning is inserted or
    changed. Two objects or malformed balanced structures are rejected.
    """
    if not isinstance(text, str):
        return RepairResultV1(None, False, False, "NO_TEXT", ("JSON_INVALID",))
    raw, valid = decode_json(text)
    if valid and isinstance(raw, dict):
        issues = schema_issues(raw, SCHEMA)
        return RepairResultV1(raw if not issues else None, not issues, not issues,
            "NONE", tuple(issue.code for issue in issues))
    stripped = text.strip()
    if stripped.startswith("```json\n") and stripped.endswith("```"):
        candidate, code = stripped[len("```json\n"):-3].strip(), "EXACT_JSON_FENCE"
    elif stripped.startswith("```\n") and stripped.endswith("```"):
        candidate, code = stripped[len("```\n"):-3].strip(), "EXACT_FENCE"
    else:
        spans = _object_slices(stripped)
        if not spans:
            return RepairResultV1(None, False, False, "NO_UNIQUE_OBJECT", ("JSON_INVALID",))
        start, end = spans[0]
        candidate, code = stripped[start:end], "UNIQUE_OBJECT_EXTRACTION"
    value, valid = decode_json(candidate)
    if not valid or not isinstance(value, dict):
        return RepairResultV1(None, False, False, code, ("JSON_INVALID",))
    issues = schema_issues(value, SCHEMA)
    return RepairResultV1(value if not issues else None, False, not issues,
        code, tuple(issue.code for issue in issues))
