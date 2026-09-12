import json

import pytest

from guardian_truth.llm_client import ChatClientError, Completion
from guardian_truth.vnext.schema_diagnostics import diagnose_completion, schema_issues
from guardian_truth.vnext.semantic_v2 import DiagnosticSemanticBackend


SCHEMA = {"type": "object", "required": ["ok"], "additionalProperties": False,
          "properties": {"ok": {"type": "boolean"}}}


@pytest.mark.parametrize("text", ['{"ok":true,"ok":false}', '{"ok":NaN}', 'not JSON'])
def test_bad_json_has_value_free_diagnostic(text):
    value, issues = diagnose_completion(text, SCHEMA)
    assert value is None and [issue.code for issue in issues] == ["JSON_INVALID"]


def test_unknown_keys_and_values_do_not_appear_in_diagnostics():
    marker = "private-credential-looking-marker"
    value, issues = diagnose_completion(json.dumps({marker: marker, "ok": marker}), SCHEMA)
    assert value is None
    assert marker not in repr(issues)
    assert {issue.code for issue in issues} == {"ADDITIONAL_PROPERTIES", "TYPE_MISMATCH"}
    assert {issue.path for issue in issues} == {"", "/ok"}


@pytest.mark.parametrize("value,schema,code", [
    (True, {"enum": [1]}, "ENUM_MISMATCH"),
    (True, {"const": 1}, "CONST_MISMATCH"),
    (4, {"type": "integer", "maximum": 3}, "ABOVE_MAXIMUM"),
    (-1, {"type": "integer", "minimum": 0}, "BELOW_MINIMUM"),
    (None, {"anyOf": [{"type": "string"}, {"type": "integer"}]}, "ANY_OF_NO_MATCH"),
    (1, {"anyOf": [{"type": "integer"}], "minimum": 2}, "BELOW_MINIMUM"),
    ([1, 1.0], {"type": "array", "uniqueItems": True}, "DUPLICATE_ITEMS"),
    ([], {"type": "array", "minItems": 1}, "TOO_FEW_ITEMS"),
    ({}, SCHEMA, "REQUIRED_PROPERTY_MISSING"),
])
def test_strict_codes(value, schema, code):
    assert code in {issue.code for issue in schema_issues(value, schema)}


def test_json_numeric_equality_and_bool_distinction():
    assert not schema_issues(1.0, {"enum": [1]})
    assert not schema_issues([1, True], {"type": "array", "uniqueItems": True})


def test_diagnostic_count_and_recursion_are_bounded():
    assert len(schema_issues(["bad"] * 100, {"type": "array", "items": {"type": "integer"}}, max_issues=3)) == 3
    assert schema_issues([[1]], {"type": "array", "items": {"type": "array", "items": {}}}, max_depth=1)[0].code == "SCHEMA_DEPTH_EXCEEDED"


class Client:
    def __init__(self, content='{"ok":true}', error=None):
        self.content, self.error, self.calls = content, error, 0

    def complete(self, messages, *, schema, reasoning_effort):
        self.calls += 1
        if self.error:
            raise self.error
        return Completion(self.content, model="qwen3.8-flash", usage={"total_tokens": 12})


def test_transport_schema_and_json_categories_are_separate():
    for client, transport, code in [(Client("bad"), "SUCCESS", "JSON_INVALID"),
            (Client('{"ok":4}'), "SUCCESS", "TYPE_MISMATCH"),
            (Client(error=ChatClientError("rate_limit")), "ERROR", None)]:
        rows = []
        result = DiagnosticSemanticBackend(client, checkpoint=rows.append).propose("task", {}, SCHEMA)
        assert result.transport_status == transport and result.value is None
        assert client.calls == 1
        assert [item["code"] for item in rows[0]["schema_issues"]] == ([code] if code else [])
        assert "content" not in rows[0]


def test_v2_backend_waits_without_retry_and_retains_no_raw_answer():
    now, waits, rows = [0.0], [], []
    def sleep(seconds):
        waits.append(seconds)
        now[0] += seconds
    client = Client()
    backend = DiagnosticSemanticBackend(client, clock=lambda: now[0], sleep=sleep, checkpoint=rows.append)
    assert backend.propose("task", {}, SCHEMA).value == {"ok": True}
    backend.propose("task", {}, SCHEMA)
    assert client.calls == 2 and waits == [10.0]
    assert rows[0]["backend_version"] == "diagnostic-semantic-v2"
    assert rows[0]["schema_issues"] == []
