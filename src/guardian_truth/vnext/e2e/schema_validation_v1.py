"""Deterministic validator for the JSON-schema subset emitted by the adapter."""

from __future__ import annotations

from ..integrity import canonical


SUPPORTED_KEYS = frozenset({"type", "properties", "required", "additionalProperties",
                            "items", "enum"})


def validate_declared_json(value, schema: dict, path: tuple[str, ...] = ()) -> tuple[bool | None, tuple[str, ...]]:
    """Return (valid, diagnostics); ``None`` means unsupported/malformed schema.

    The accepted language is exactly the source adapter's structural subset.
    Unknown keywords never become violations: they fail closed to UNKNOWN.
    """
    location = "/" + "/".join(path) if path else "/"
    if not isinstance(schema, dict):
        return None, ("MALFORMED_SCHEMA:" + location,)
    unknown = sorted(set(schema) - SUPPORTED_KEYS)
    if unknown:
        return None, tuple("UNSUPPORTED_SCHEMA_KEYWORD:" + key for key in unknown)
    if not schema:
        return True, ()

    kind = schema.get("type")
    predicates = {
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
        "null": lambda item: item is None,
    }
    if kind not in predicates:
        return None, ("UNSUPPORTED_SCHEMA_TYPE:" + repr(kind),)
    if not predicates[kind](value):
        return False, (f"TYPE:{location}:{kind}",)

    enum = schema.get("enum")
    if enum is not None:
        if not isinstance(enum, list):
            return None, ("MALFORMED_ENUM:" + location,)
        encoded = canonical(value)
        if all(canonical(candidate) != encoded for candidate in enum):
            return False, ("ENUM:" + location,)

    errors: list[str] = []
    if kind == "object":
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        additional = schema.get("additionalProperties", True)
        if (not isinstance(properties, dict) or not isinstance(required, list)
                or any(not isinstance(key, str) for key in required)
                or not isinstance(additional, bool)):
            return None, ("MALFORMED_OBJECT_SCHEMA:" + location,)
        errors.extend("REQUIRED:" + "/".join((*path, key))
                      for key in required if key not in value)
        if not additional:
            errors.extend("ADDITIONAL:" + "/".join((*path, key))
                          for key in value if key not in properties)
        for key in sorted(set(value) & set(properties)):
            valid, nested = validate_declared_json(value[key], properties[key], (*path, key))
            if valid is None:
                return None, nested
            if not valid:
                errors.extend(nested)
    elif kind == "array":
        items = schema.get("items", {})
        if not isinstance(items, dict):
            return None, ("MALFORMED_ITEMS:" + location,)
        for index, item in enumerate(value):
            valid, nested = validate_declared_json(item, items, (*path, str(index)))
            if valid is None:
                return None, nested
            if not valid:
                errors.extend(nested)
    return not errors, tuple(errors)
