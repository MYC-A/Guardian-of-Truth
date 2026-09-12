"""Value-free strict JSON/schema diagnostics. Never report model values or keys."""

from dataclasses import dataclass

from guardian_truth.parsing import decode_json


@dataclass(frozen=True)
class SchemaIssue:
    code: str
    path: str
    expected_type: str | None = None
    actual_type: str | None = None


def json_type(value):
    if value is None:
        return "null"
    if type(value) is bool:
        return "boolean"
    if type(value) is int:
        return "integer"
    if type(value) is float:
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unsupported"


def json_equal(left, right):
    """JSON equality: booleans are not numbers; object order is immaterial."""
    left_type, right_type = json_type(left), json_type(right)
    if left_type != right_type and {left_type, right_type} != {"integer", "number"}:
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(json_equal(left[key], right[key]) for key in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(json_equal(a, b) for a, b in zip(left, right))
    return left == right


def schema_issues(value, schema, *, max_issues=16, max_depth=64):
    if type(max_issues) is not int or max_issues < 1:
        raise ValueError("positive diagnostic bound required")
    issues = []

    def emit(code, path, expected=None, actual=None):
        if len(issues) < max_issues:
            issues.append(SchemaIssue(code, path, expected, actual))

    def visit(item, spec, path, depth):
        if len(issues) >= max_issues:
            return
        if depth > max_depth:
            emit("SCHEMA_DEPTH_EXCEEDED", path)
            return
        if "anyOf" in spec:
            if all(schema_issues(item, child, max_issues=1, max_depth=max_depth - depth)
                   for child in spec["anyOf"]):
                emit("ANY_OF_NO_MATCH", path)
                return
        expected = spec.get("type")
        actual = json_type(item)
        if expected and actual != expected and not (expected == "number" and actual == "integer"):
            emit("TYPE_MISMATCH", path, expected, actual)
            return
        if "enum" in spec and not any(json_equal(item, choice) for choice in spec["enum"]):
            emit("ENUM_MISMATCH", path)
        if "const" in spec and not json_equal(item, spec["const"]):
            emit("CONST_MISMATCH", path)
        if type(item) in {int, float}:
            if "minimum" in spec and item < spec["minimum"]:
                emit("BELOW_MINIMUM", path)
            if "maximum" in spec and item > spec["maximum"]:
                emit("ABOVE_MAXIMUM", path)
        if isinstance(item, dict):
            properties = spec.get("properties", {})
            if any(key not in item for key in spec.get("required", ())):
                emit("REQUIRED_PROPERTY_MISSING", path)
            if spec.get("additionalProperties") is False and any(key not in properties for key in item):
                # Unknown keys may themselves contain credential-looking text.
                # Their values and names never enter the diagnostic.
                emit("ADDITIONAL_PROPERTIES", path)
            for key, child in properties.items():
                if key in item:
                    # Paths use declared schema-owned property names ONLY.
                    owned_key = key.replace("~", "~0").replace("/", "~1")
                    visit(item[key], child, path + "/" + owned_key, depth + 1)
        if isinstance(item, list):
            if len(item) < spec.get("minItems", 0):
                emit("TOO_FEW_ITEMS", path)
            if len(item) > spec.get("maxItems", float("inf")):
                emit("TOO_MANY_ITEMS", path)
            if spec.get("uniqueItems") and any(json_equal(child, previous)
                    for index, child in enumerate(item) for previous in item[:index]):
                emit("DUPLICATE_ITEMS", path)
            for index, child in enumerate(item):
                visit(child, spec.get("items", {}), path + "/" + str(index), depth + 1)

    visit(value, schema, "", 0)
    return tuple(issues)


def diagnose_completion(text, schema):
    value, valid_json = decode_json(text)
    if not valid_json:
        return None, (SchemaIssue("JSON_INVALID", ""),)
    issues = schema_issues(value, schema)
    return value if not issues else None, issues
