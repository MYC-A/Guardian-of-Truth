"""Source-certified target-call membership and its metamorphic boundary."""

from guardian_truth.vnext.adapters import AdapterMode
from guardian_truth.vnext.e2e.core_v1 import GuardianE2EV1
from guardian_truth.vnext.e2e.e2e_types_v1 import E2ECaseInput
from guardian_truth.vnext.e2e.source_adapter_v1 import (build_source, declared_tool_catalog,
                                                        tool_catalog)
from guardian_truth.vnext.semantic import Proposal
from guardian_truth.vnext.types import CoreStatus


class NoSemanticBackend:
    def propose(self, task, payload, schema):  # pragma: no cover - a call is a test failure
        raise AssertionError(f"structural catalog validation called semantic backend: {task}")


class FailingSemanticBackend:
    def propose(self, task, payload, schema):
        return Proposal(None, "ERROR", "NOT_RUN", "deliberate_frontend_failure")


def analyze(*, declared_tool: str, called_tool: str, entity: str = "R-7",
            catalog_complete: bool = True):
    case = E2ECaseInput(
        case_id="catalog-pair", family="source_catalog_membership",
        system_policy="", user_request="", history=(),
        target_response=(f'⟦ASSISTANT_TOOL_CALL name="{called_tool}" call_id="target"⟧\n'
                         f'{{"record_id":"{entity}"}}'),
        tool_metadata=({"name": declared_tool},),
        tool_schemas=({"name": declared_tool,
                       "parameters": {"type": "object", "properties": {
                           "record_id": {"type": "string"}}, "required": ["record_id"]}},),
        tool_catalog_complete=catalog_complete,
        history_complete=True, completeness_basis="explicit complete test history",
    )
    return GuardianE2EV1(NoSemanticBackend(), adapter_mode=AdapterMode.COMPETITION,
                         enable_t2=False).analyze_e2e_v1(case)


def test_unavailable_target_tool_is_certified_error_but_declared_tool_is_not():
    violation = analyze(declared_tool="inspect_record", called_tool="erase_record")
    control = analyze(declared_tool="inspect_record", called_tool="inspect_record")

    assert violation.result.status is CoreStatus.PROVED_ERROR
    assert violation.result.certificate_check.valid
    assert violation.product_decision.binary_label == 1
    assert control.result.status is CoreStatus.PROVED_NO_ERROR
    assert control.result.certificate_check.valid
    assert control.product_decision.binary_label == 0


def test_catalog_membership_is_invariant_under_tool_and_entity_renaming():
    original = analyze(declared_tool="inspect_record", called_tool="erase_record", entity="R-7")
    renamed = analyze(declared_tool="lookup_object", called_tool="remove_object", entity="OBJ-991")
    renamed_control = analyze(declared_tool="lookup_object", called_tool="lookup_object",
                              entity="OBJ-991")

    assert original.result.status is renamed.result.status is CoreStatus.PROVED_ERROR
    assert original.product_decision.binary_label == renamed.product_decision.binary_label == 1
    assert renamed_control.result.status is CoreStatus.PROVED_NO_ERROR


def test_observed_call_names_do_not_invent_catalog_completeness():
    analysis = analyze(declared_tool="inspect_record", called_tool="erase_record",
                       catalog_complete=False)
    assert analysis.result.status is not CoreStatus.PROVED_ERROR


def test_structural_catalog_does_not_change_frozen_frontend_catalog():
    case = E2ECaseInput(
        case_id="catalog-isolation", family="source_catalog_membership",
        system_policy="", user_request="", history=(),
        target_response='⟦ASSISTANT_TOOL_CALL name="erase_record"⟧\n{}',
        tool_metadata=({"name": "inspect_record"},),
        tool_schemas=({"name": "inspect_record", "parameters": {"type": "object"}},),
        tool_catalog_complete=True,
    )
    source = build_source(case)
    assert declared_tool_catalog(source) == ("inspect_record",)
    assert tool_catalog(source) == ("erase_record", "inspect_record")


def test_source_invariant_violation_survives_unrelated_incomplete_policy_axis():
    case = E2ECaseInput(
        case_id="catalog-incomplete-policy", family="source_catalog_membership",
        system_policy="A deliberately unresolved natural-language policy.", user_request="",
        history=(), target_response='⟦ASSISTANT_TOOL_CALL name="erase_record"⟧\n{}',
        tool_metadata=({"name": "inspect_record"},),
        tool_schemas=({"name": "inspect_record", "parameters": {"type": "object"}},),
        tool_catalog_complete=True,
    )
    analysis = GuardianE2EV1(
        FailingSemanticBackend(), adapter_mode=AdapterMode.COMPETITION,
        enable_t2=False).analyze_e2e_v1(case)
    assert analysis.frontend_statuses
    assert analysis.result.status is CoreStatus.PROVED_ERROR
    assert analysis.result.certificate_check.valid
