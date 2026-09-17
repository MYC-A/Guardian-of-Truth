import json

from guardian_truth.vnext.adapters import AdapterMode
from guardian_truth.vnext.e2e.core_v1 import GuardianE2EV1
from guardian_truth.vnext.e2e.e2e_types_v1 import E2ECaseInput
from guardian_truth.vnext.e2e.schema_validation_v1 import validate_declared_json
from guardian_truth.vnext.semantic import Proposal
from guardian_truth.vnext.types import CoreStatus


SCHEMA = {
    "type": "object",
    "properties": {
        "payment_methods": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "payment_id": {"type": "string"},
                    "amount": {"type": "integer"},
                },
                "required": ["payment_id", "amount"],
                "additionalProperties": False,
            },
        },
        "mode": {"type": "string", "enum": ["brief", "full"]},
    },
    "required": ["payment_methods"],
    "additionalProperties": False,
}


def test_nested_required_types_enum_and_additional_fields():
    valid = {"payment_methods": [{"payment_id": "gift-7", "amount": 50}], "mode": "brief"}
    invalid = {"payment_methods": [{"id": "gift-7", "source": "gift", "amount": "50"}],
               "mode": "verbose"}
    assert validate_declared_json(valid, SCHEMA) == (True, ())
    accepted, errors = validate_declared_json(invalid, SCHEMA)
    assert accepted is False
    assert {item.split(":", 1)[0] for item in errors} == {
        "REQUIRED", "ADDITIONAL", "TYPE", "ENUM"}


def test_unknown_schema_keyword_is_unknown_not_violation():
    accepted, errors = validate_declared_json("x", {"type": "string", "pattern": "x"})
    assert accepted is None
    assert errors == ("UNSUPPORTED_SCHEMA_KEYWORD:pattern",)


def test_field_and_value_renaming_preserves_structural_result():
    renamed_schema = {
        "type": "object", "properties": {"widget": {"type": "integer"}},
        "required": ["widget"], "additionalProperties": False,
    }
    assert validate_declared_json({"amount": 7}, {
        "type": "object", "properties": {"amount": {"type": "integer"}},
        "required": ["amount"], "additionalProperties": False}) == (True, ())
    assert validate_declared_json({"widget": 991}, renamed_schema) == (True, ())


class NoSemanticBackend:
    def propose(self, task, payload, schema):  # pragma: no cover
        raise AssertionError(task)


class FailingSemanticBackend:
    def propose(self, task, payload, schema):
        return Proposal(None, "ERROR", "NOT_RUN", "deliberate_frontend_failure")


def analyze_call(tool, payload, schema, *, policy="", backend=None):
    case = E2ECaseInput(
        case_id="schema-pair", family="declared_schema_validity",
        system_policy=policy, user_request="", history=(),
        target_response=(f'⟦ASSISTANT_TOOL_CALL name="{tool}" call_id="target"⟧\n'
                         + json.dumps(payload)),
        tool_metadata=({"name": tool},),
        tool_schemas=({"name": tool, "parameters": schema},),
        tool_catalog_complete=True,
        history_complete=True, completeness_basis="explicit complete test history",
    )
    return GuardianE2EV1(backend or NoSemanticBackend(),
                         adapter_mode=AdapterMode.COMPETITION,
                         enable_t2=False).analyze_e2e_v1(case)


def test_invalid_declared_arguments_are_certified_but_valid_control_is_not():
    invalid = analyze_call("charge", {"id": "gift-7"}, {
        "type": "object", "properties": {"payment_id": {"type": "string"}},
        "required": ["payment_id"], "additionalProperties": False})
    control = analyze_call("charge", {"payment_id": "gift-7"}, {
        "type": "object", "properties": {"payment_id": {"type": "string"}},
        "required": ["payment_id"], "additionalProperties": False})
    assert invalid.result.status is CoreStatus.PROVED_ERROR
    assert invalid.result.certificate_check.valid
    assert control.result.status is CoreStatus.PROVED_NO_ERROR
    assert control.result.certificate_check.valid


def test_schema_violation_is_invariant_to_tool_field_and_value_renaming():
    first = analyze_call("charge", {"wrong": "gift-7"}, {
        "type": "object", "properties": {"payment_id": {"type": "string"}},
        "required": ["payment_id"], "additionalProperties": False})
    renamed = analyze_call("allocate_widget", {"other": 991}, {
        "type": "object", "properties": {"widget": {"type": "integer"}},
        "required": ["widget"], "additionalProperties": False})
    assert first.result.status is renamed.result.status is CoreStatus.PROVED_ERROR


def test_unsupported_schema_is_unknown_not_certified_error():
    analysis = analyze_call("match_text", {"value": "y"}, {
        "type": "object", "properties": {"value": {"type": "string", "pattern": "x"}},
        "required": ["value"], "additionalProperties": False})
    assert analysis.result.status is CoreStatus.UNRESOLVED


def test_schema_violation_survives_unrelated_incomplete_policy_axis():
    analysis = analyze_call("charge", {"id": "gift-7"}, {
        "type": "object", "properties": {"payment_id": {"type": "string"}},
        "required": ["payment_id"], "additionalProperties": False},
        policy="A deliberately unresolved natural-language policy.",
        backend=FailingSemanticBackend())
    assert analysis.frontend_statuses
    assert analysis.result.status is CoreStatus.PROVED_ERROR
    assert analysis.result.certificate_check.valid
