"""Adversarial and metamorphic tests for the closure-premise separation.

Covers the hidden-assumption audit requirements:

Catalog (open vs closed universe):
  A. declared tool called -> structurally fine, no catalog marker
  B. undeclared tool called, universe not source-closed -> UNKNOWN, never ERROR
  C. dynamic discovery (history result announces a new tool) -> still UNKNOWN
  D. bootstrap discovery tool returning generated names -> UNKNOWN
  E. aliased/versioned names (foo, foo.v2, foo.v3) -> UNKNOWN for foo.v3
  F. closed-universe premise established -> absence certifies ERROR (capability kept)

Schema (DECLARED_FIELDS vs OBJECT_CLOSED):
  A. required field missing ("!") -> certified violation (source-explicit)
  B. enum violation -> certified violation (source-explicit)
  C. extra field without OBJECT_CLOSED -> never a certified violation
  D. nested required missing -> certified violation
  E. unsupported schema syntax -> UNKNOWN, never guessed violation
  F. extra field WITH OBJECT_CLOSED -> certified violation (capability kept)
  G. type mismatch (declared integer, JSON string) -> certified violation

Counterfactual soundness: adding "other tools may be dynamically available"
or "additional properties are allowed" text must not change the corrected
behavior (it already abstains), and must not leave the old over-strong
certification in place.
"""

import json

from guardian_truth.vnext.adapters import AdapterMode
from guardian_truth.vnext.e2e.core_v1 import GuardianE2EV1
from guardian_truth.vnext.e2e.e2e_types_v1 import E2ECaseInput
from guardian_truth.vnext.e2e.schema_validation_v1 import (certification_schema,
                                                           validate_declared_json)
from guardian_truth.vnext.types import CoreStatus


class NoSemanticBackend:
    def propose(self, task, payload, schema):  # pragma: no cover - a call is a test failure
        raise AssertionError(f"structural validation called semantic backend: {task}")


class FailingSemanticBackend:
    def propose(self, task, payload, schema):
        from guardian_truth.vnext.semantic import Proposal
        return Proposal(None, "ERROR", "NOT_RUN", "deliberate_frontend_failure")


def analyze(*, tools, called, payload=None, policy="", history=(),
            tool_universe_closed=False, object_fields_closed=False, schemas=None,
            history_complete=True, backend=None):
    if schemas is None:
        schemas = {name: {"type": "object", "properties": {"record_id": {"type": "string"}},
                           "required": ["record_id"]} for name in tools}
    tool_schema_items = tuple({"name": name, "parameters": schema}
                              for name, schema in schemas.items())
    body = json.dumps({"record_id": "R-7"} if payload is None else payload)
    case = E2ECaseInput(
        case_id="closure-pair", family="closure_premise_audit",
        system_policy=policy, user_request="", history=history,
        target_response=(f'⟦ASSISTANT_TOOL_CALL name="{called}" call_id="target"⟧\n' + body),
        tool_metadata=tuple({"name": name} for name in schemas),
        tool_schemas=tool_schema_items,
        tool_catalog_complete=True,
        tool_universe_closed=tool_universe_closed,
        object_fields_closed=object_fields_closed,
        history_complete=history_complete, completeness_basis="explicit complete test history",
    )
    return GuardianE2EV1(backend or NoSemanticBackend(), adapter_mode=AdapterMode.COMPETITION,
                         enable_t2=False).analyze_e2e_v1(case)


def marker_ids(analysis):
    # Markers enter world safety as explicit UNKNOWN conjuncts.
    return [obligation_id
            for proof in analysis.result.world_proofs
            for obligation_id, value in proof.obligation_safety
            if value.value == "UNKNOWN" and ":open-universe:" in obligation_id]


def catalog_markers(analysis):
    return [item for item in marker_ids(analysis)
            if item.startswith("source:declared-tool-membership:open-universe:")]


# --------------------------------------------------------------- catalog A-F

def test_catalog_A_declared_tool_call_has_no_marker_and_may_certify_no_error():
    analysis = analyze(tools=("inspect_record",), called="inspect_record",
                       payload={"record_id": "R-7"})
    assert analysis.result.status is CoreStatus.PROVED_NO_ERROR
    assert analysis.result.certificate_check.valid
    assert catalog_markers(analysis) == []


def test_catalog_B_undeclared_call_is_unknown_never_error_without_closure():
    analysis = analyze(tools=("inspect_record", "beta_action"), called="erase_record")
    assert analysis.result.status is CoreStatus.UNRESOLVED
    assert analysis.result.status is not CoreStatus.PROVED_ERROR
    assert analysis.product_decision.binary_label == 0
    assert catalog_markers(analysis)  # explicit UNKNOWN trail present


def test_catalog_B2_undeclared_call_blocks_no_error_certification():
    # even a fully-valid-looking trajectory cannot certify safety while an
    # out-of-catalog call remains unexplained
    analysis = analyze(tools=("inspect_record",), called="erase_record",
                       payload={"record_id": "R-7"})
    assert analysis.result.status is not CoreStatus.PROVED_NO_ERROR
    assert analysis.result.status is CoreStatus.UNRESOLVED


def test_catalog_C_dynamic_discovery_counterfactual_stays_unknown():
    history = ('⟦ASSISTANT_TOOL_CALL name="discover" call_id="h1"⟧\n{"topic":"diagnostics"}\n'
               '⟦TOOL_RESULT requestor="assistant" name="discover" call_id="h1"⟧\n'
               '{"message":"tool gamma_action is now available for this session"}')
    analysis = analyze(tools=("discover",), called="gamma_action", history=history,
                       payload={"record_id": "R-7"})
    assert analysis.result.status is CoreStatus.UNRESOLVED
    assert analysis.result.status is not CoreStatus.PROVED_ERROR


def test_catalog_D_bootstrap_discovery_generated_name_stays_unknown():
    history = ('⟦ASSISTANT_TOOL_CALL name="list_actions" call_id="h1"⟧\n{}\n'
               '⟦TOOL_RESULT requestor="assistant" name="list_actions" call_id="h1"⟧\n'
               '{"actions":[{"name":"generated_action_8417"}]}')
    analysis = analyze(tools=("list_actions",), called="generated_action_8417",
                       history=history, payload={"record_id": "R-7"})
    assert analysis.result.status is CoreStatus.UNRESOLVED


def test_catalog_E_versioned_alias_names_stay_unknown():
    analysis = analyze(tools=("foo", "foo.v2"), called="foo.v3",
                       payload={"record_id": "R-7"})
    assert analysis.result.status is CoreStatus.UNRESOLVED
    assert catalog_markers(analysis)


def test_catalog_F_closed_universe_premise_still_certifies_absence():
    analysis = analyze(tools=("inspect_record",), called="erase_record",
                       tool_universe_closed=True)
    assert analysis.result.status is CoreStatus.PROVED_ERROR
    assert analysis.result.certificate_check.valid


def test_catalog_counterfactual_dynamic_availability_text_changes_nothing():
    # "Other tools may be dynamically available." explicitly stated:
    # corrected behavior already abstains; it must not certify ERROR.
    policy = ("Other tools may be dynamically available during the session. "
              "A deliberately unresolved natural-language policy.")
    analysis = analyze(tools=("inspect_record",), called="erase_record", policy=policy,
                       backend=FailingSemanticBackend())
    assert analysis.result.status is CoreStatus.UNRESOLVED


# ---------------------------------------------------------------- schema A-G

SCHEMA_FIELDS = {
    "type": "object",
    "properties": {
        "payment_id": {"type": "string"},
        "amount": {"type": "integer"},
        "mode": {"type": "string", "enum": ["brief", "full"]},
    },
    "required": ["payment_id", "amount"],
    "additionalProperties": False,
}


def schema_analyze(payload, *, object_fields_closed=False, schema=None):
    return analyze(tools=("charge",), called="charge", payload=payload,
                   schemas={"charge": schema or SCHEMA_FIELDS},
                   object_fields_closed=object_fields_closed)


def test_schema_A_missing_required_field_is_certified_violation():
    analysis = schema_analyze({"payment_id": "gift-7"})
    assert analysis.result.status is CoreStatus.PROVED_ERROR
    assert analysis.result.certificate_check.valid


def test_schema_B_enum_violation_is_certified():
    analysis = schema_analyze({"payment_id": "gift-7", "amount": 5, "mode": "verbose"})
    assert analysis.result.status is CoreStatus.PROVED_ERROR


def test_schema_C_extra_field_alone_is_not_a_violation_without_object_closure():
    analysis = schema_analyze({"payment_id": "gift-7", "amount": 5,
                               "metadata": {"note": "user asked"}})
    assert analysis.result.status is CoreStatus.PROVED_NO_ERROR
    assert analysis.result.certificate_check.valid


def test_schema_C2_counterfactual_explicit_allow_additional_properties():
    policy = ("Additional properties are allowed on every tool argument object. "
              "A deliberately unresolved natural-language policy.")
    analysis = schema_analyze({"payment_id": "gift-7", "amount": 5, "extra": 1},
                              schema=dict(SCHEMA_FIELDS, additionalProperties=True))
    assert analysis.result.status is CoreStatus.PROVED_NO_ERROR


def test_schema_D_nested_required_missing_is_certified():
    schema = {"type": "object",
              "properties": {"customer": {"type": "object",
                                          "properties": {"id": {"type": "string"}},
                                          "required": ["id"],
                                          "additionalProperties": False}},
              "required": ["customer"], "additionalProperties": False}
    analysis = schema_analyze({"customer": {"name": "x"}}, schema=schema)
    assert analysis.result.status is CoreStatus.PROVED_ERROR


def test_schema_E_unsupported_syntax_stays_unknown():
    analysis = schema_analyze({"payment_id": "gift-7", "amount": 5},
                              schema={"type": "object",
                                      "properties": {"amount": {"type": "integer",
                                                                "minimum": 0}},
                                      "required": ["amount"]})
    assert analysis.result.status is CoreStatus.UNRESOLVED


def test_schema_F_object_closed_premise_still_certifies_extra_fields():
    analysis = schema_analyze({"payment_id": "gift-7", "amount": 5, "extra": 1},
                              object_fields_closed=True)
    assert analysis.result.status is CoreStatus.PROVED_ERROR
    assert analysis.result.certificate_check.valid


def test_schema_G_declared_type_mismatch_is_certified():
    analysis = schema_analyze({"payment_id": "gift-7", "amount": "5"})
    assert analysis.result.status is CoreStatus.PROVED_ERROR


# ------------------------------------------------- certification_schema unit

def test_certification_schema_strips_only_closure_markers():
    stripped = certification_schema(SCHEMA_FIELDS, object_fields_closed=False)
    assert "additionalProperties" not in json.dumps(stripped)
    assert stripped["required"] == ["payment_id", "amount"]
    assert set(stripped["properties"]) == {"payment_id", "amount", "mode"}
    assert stripped["properties"]["mode"]["enum"] == ["brief", "full"]


def test_certification_schema_keeps_source_established_closure():
    kept = certification_schema(SCHEMA_FIELDS, object_fields_closed=True)
    assert kept == SCHEMA_FIELDS


def test_open_universe_schema_validation_ignores_extra_fields():
    stripped = certification_schema(SCHEMA_FIELDS, object_fields_closed=False)
    assert validate_declared_json({"payment_id": "g", "amount": 1, "x": 2}, stripped) == (True, ())
    valid, errors = validate_declared_json({"amount": 1, "x": 2}, stripped)
    assert valid is False
    assert errors == ("REQUIRED:payment_id",)


# --------------------------------------------------- no-manufactured-ERROR

def test_no_false_witness_is_ever_manufactured_without_closure():
    for setup in (
        dict(tools=("a_tool",), called="b_tool"),                       # open catalog
        dict(tools=("a_tool",), called="a_tool",                        # extra field
             payload={"record_id": "R-7", "note": "x"}),
    ):
        analysis = analyze(**setup)
        witnesses = [entry for proof in analysis.result.world_proofs
                     for entry in proof.obligation_safety if entry[1].value == "FALSE"]
        assert analysis.result.status is not CoreStatus.PROVED_ERROR or not witnesses
        if setup["called"] not in setup["tools"]:
            assert analysis.result.status is CoreStatus.UNRESOLVED
