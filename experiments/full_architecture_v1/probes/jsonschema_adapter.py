"""full_architecture_v1 — Phase B probe: jsonschema replacement experiment (directive §5).

Question: can the custom ``schema_validation_v1.validate_declared_json`` walk be
replaced by the mature ``jsonschema`` package behind a thin Guardian adapter,
with diagnostic parity on the shared language?

Design (thin adapter — three fences stay ours, checking is delegated):
  1. GATE (fail-closed soundness fence, mirrors the incumbent's control flow):
     unsupported keyword / unsupported type / malformed schema -> UNKNOWN (None);
     nested gating follows the incumbent's recursion (only keys present in the
     value, only after the parent type matched).
  2. VERDICT + generic constraint checking: jsonschema Draft 2020-12
     ``iter_errors`` (type/enum/required/additionalProperties at every depth).
  3. DIAGNOSTICS: converted to the incumbent's exact typed format
     ("TYPE:/p:kind" (leading slash), "REQUIRED:p/key" & "ADDITIONAL:p/key"
     (NO leading slash), "ENUM:/p", "MALFORMED_*", "UNSUPPORTED_*").

Documented normalizations (measured by the probe, never hidden):
  N1. incumbent "integer" rejects 3.0; jsonschema Draft6+ accepts integral
      floats -> adapter enforces incumbent semantics (scan at every depth).
  N2. jsonschema collapses additionalProperties messages per object ->
      adapter recomputes per-key diagnostics at the error's location.
  N3. diagnostic ORDER differs; the probe compares verdicts + diagnostic SETS
      and reports order as non-semantic.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

import jsonschema

_ALLOWED_TYPES = ("object", "array", "string", "integer", "number",
                  "boolean", "null")
_PY_TYPE_OK = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}
_JS_INTEGER_OK = jsonschema.Draft202012Validator({"type": "integer"}).is_valid
_REQUIRED_KEY = re.compile(r"'(.*)' is a required property")


def _loc(path: tuple[str, ...]) -> str:
    return "/" + "/".join(path) if path else "/"


def _flat(path: tuple[str, ...]) -> str:
    """Incumbent REQUIRED/ADDITIONAL path format: no leading slash."""
    return "/".join(path)


# --------------------------------------------------------------- gate (fence)

def _gate(schema, value, path: tuple[str, ...] = ()) -> tuple[str, ...] | None:
    """Fail-closed scan mirroring the incumbent's control flow.

    Returns a diagnostics tuple when the result must be UNKNOWN (None-valid);
    returns None when the pair passes the fence (verdict then comes from
    jsonschema).  Value-gated exactly like the incumbent: children are only
    inspected where the value actually has data.
    """
    if not isinstance(schema, dict):
        return ("MALFORMED_SCHEMA:" + _loc(path),)
    unknown = sorted(set(schema) - {"type", "properties", "required",
                                    "additionalProperties", "items", "enum"})
    if unknown:
        return tuple("UNSUPPORTED_SCHEMA_KEYWORD:" + key for key in unknown)
    if not schema:
        return None
    kind = schema.get("type")
    if kind not in _ALLOWED_TYPES:
        return ("UNSUPPORTED_SCHEMA_TYPE:" + repr(kind),)
    if not _PY_TYPE_OK[kind](value):
        # incumbent short-circuits False:TYPE here; jsonschema emits the type
        # error itself, so the gate has nothing more to inspect
        return None
    enum = schema.get("enum")
    if enum is not None and not isinstance(enum, list):
        return ("MALFORMED_ENUM:" + _loc(path),)
    if kind == "object":
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        additional = schema.get("additionalProperties", True)
        if (not isinstance(properties, dict) or not isinstance(required, list)
                or any(not isinstance(key, str) for key in required)
                or not isinstance(additional, bool)):
            return ("MALFORMED_OBJECT_SCHEMA:" + _loc(path),)
        if not isinstance(value, dict):
            return None
        for key in sorted(set(value) & set(properties)):
            problem = _gate(properties[key], value[key], (*path, key))
            if problem is not None:
                return problem
    elif kind == "array":
        items = schema.get("items", {})
        if not isinstance(items, dict):
            return ("MALFORMED_ITEMS:" + _loc(path),)
        if not isinstance(value, list):
            return None
        for index, item in enumerate(value):
            problem = _gate(items, item, (*path, str(index)))
            if problem is not None:
                return problem
    return None


# ------------------------------------------------- N1: integral float scan

def _integer_float_scan(value, schema: dict, path: tuple[str, ...] = ()) \
        -> list[str]:
    """Incumbent semantics: 3.0 is NOT an "integer" at any depth.

    jsonschema never reports these; the scan walks exactly where the
    incumbent's recursion would walk.
    """
    out: list[str] = []
    if not isinstance(schema, dict):
        return out
    kind = schema.get("type")
    if kind == "integer" and isinstance(value, float) \
            and value.is_integer() and _JS_INTEGER_OK(value):
        out.append(f"TYPE:{_loc(path)}:integer")
    if kind == "object" and isinstance(value, dict):
        properties = schema.get("properties", {})
        for key in sorted(set(value) & set(properties)):
            out.extend(_integer_float_scan(
                value[key], properties[key], (*path, key)))
    elif kind == "array" and isinstance(value, list):
        items = schema.get("items", {})
        for index, item in enumerate(value):
            out.extend(_integer_float_scan(item, items, (*path, str(index))))
    return out


# ------------------------------------------------------------- path walkers

def _schema_at(schema, absolute_path):
    node = schema
    for part in absolute_path:
        if isinstance(node, dict) and part in node.get("properties", {}):
            node = node["properties"][part]
        elif isinstance(node, dict) and "items" in node:
            node = node["items"]
        else:
            return None
    return node


def _value_at(value, absolute_path):
    node = value
    for part in absolute_path:
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and str(part).isdigit() \
                and int(part) < len(node):
            node = node[int(part)]
        else:
            return None
    return node


# --------------------------------------------------------------- main entry

def validate_with_jsonschema(value, schema: dict,
                             path: tuple[str, ...] = ()):
    """Thin Guardian adapter over jsonschema (incumbent return contract).

    Returns (valid, diagnostics); valid=None means UNKNOWN (fail-closed).
    """
    problem = _gate(schema, value, path)
    if problem is not None:
        return None, problem
    if not schema:
        return True, ()

    kind = schema.get("type")
    # N1 root-level short-circuit (incumbent returns False:TYPE immediately)
    if kind == "integer" and isinstance(value, float) \
            and value.is_integer() and _JS_INTEGER_OK(value):
        return False, (f"TYPE:{_loc(path)}:integer",)

    validator = jsonschema.Draft202012Validator(schema)
    errors = list(validator.iter_errors(value))
    diagnostics: list[str] = []

    for error in errors:
        sub = (*path, *(str(part) for part in error.absolute_path))
        if error.validator == "type":
            expected = (schema.get("type") if not error.absolute_path
                        else _type_at(schema, error.absolute_path))
            diagnostics.append(f"TYPE:{_loc(sub)}:{expected}")
        elif error.validator == "enum":
            diagnostics.append(f"ENUM:{_loc(sub)}")
        elif error.validator == "required":
            match = _REQUIRED_KEY.match(error.message)
            key = match.group(1) if match else "?"
            diagnostics.append(f"REQUIRED:{_flat((*sub, key))}")
        elif error.validator == "additionalProperties":
            # N2: recompute per-key diagnostics at the error's location
            schema_at = _schema_at(schema, error.absolute_path)
            value_at = _value_at(value, error.absolute_path)
            if isinstance(schema_at, dict) and isinstance(value_at, dict):
                properties = schema_at.get("properties", {})
                for key in value_at:
                    if key not in properties:
                        diagnostics.append(f"ADDITIONAL:{_flat((*sub, key))}")
            else:  # pragma: no cover — defensive
                diagnostics.append(f"ADDITIONAL:{_flat(sub)}")
        else:  # pragma: no cover — the gate forbids other validators
            return None, ("UNSUPPORTED_SCHEMA_KEYWORD:" + str(error.validator),)

    # N1 at nested depths (jsonschema never reports these)
    diagnostics.extend(_integer_float_scan(value, schema, path))

    return (not (errors or diagnostics)), tuple(dict.fromkeys(diagnostics))


def _type_at(schema: dict, absolute_path) -> str | None:
    node = _schema_at(schema, absolute_path)
    return node.get("type") if isinstance(node, dict) else None
