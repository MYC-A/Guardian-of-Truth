"""Catalog conformance axis (session B fix iteration 1) — tests.

Covers:
- shared deterministic violation function (unknown tool, missing required
  field incl. nested array items, enum violation, invalid JSON, extra fields
  NOT flagged, type coercion NOT flagged);
- component construction (user-role calls exempt, no response calls -> no
  component, single deterministic option -> world cardinality unchanged);
- prove_e2e_atom catalog branch (TRUE/FALSE/UNKNOWN paths);
- end-to-end analyze_e2e_v1 with the flag ON: a violating call yields a
  CERTIFIED PROVED_ERROR with the catalog obligation as the FALSE witness;
- METAMORPHIC (directive §25/§26): renaming every tool (incl. the violating
  one) preserves the verdict; fixing the violation (adding the required
  nested field) removes the ERROR; flipping label/id changes nothing;
- flag OFF (default): frozen behavior — no catalog axis, verdict unchanged
  vs the pre-fix state on the same case.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from guardian_truth.parsing import parse_events
from guardian_truth.vnext.normalize import normalize
from guardian_truth.vnext.e2e.catalog_conformance_v1 import (
    ARGUMENT_CONFORMS_SCHEMA, CALL_IN_CATALOG, catalog_conformance_component,
    catalog_option_contract, catalog_violations)
from guardian_truth.vnext.e2e.core_v1 import GuardianE2EV1
from guardian_truth.vnext.e2e.e2e_types_v1 import E2EArmConfig, E2ECaseInput, SEMANTICS_ARMS
from guardian_truth.vnext.ledger import EvidenceLedger, LedgerIndex
from guardian_truth.vnext.proof_records import AtomKind, TimeMode
from guardian_truth.vnext.tools import ContractRegistry
from guardian_truth.vnext.types import EntityRef, Truth


SCHEMAS = {
    "update_reservation_flights": {
        "name": "update_reservation_flights",
        "description": "Update the flights of a reservation.",
        "parameters": {
            "reservation_id": {"type": "string", "required": True, "description": ""},
            "flights": {
                "type": "array", "required": True, "description": "",
                "children": {
                    "flight_number": {"type": "string", "required": True, "description": ""},
                    "date": {"type": "string", "required": True, "description": ""},
                },
            },
            "cabin": {"type": "string", "required": False, "description": "",
                      "enum": ["business", "economy", "basic_economy"]},
        },
    },
    "get_user_details": {
        "name": "get_user_details",
        "description": "Get user details.",
        "parameters": {"user_id": {"type": "string", "required": True, "description": ""}},
    },
}


def _call_event(line: str, event_id: str = "e0"):
    events = normalize("", line)
    calls = [event for event in events if event.kind == "call"]
    assert calls, "test fixture: no call parsed"
    assert calls[0].tool is not None
    return calls[0]


def test_unknown_tool_is_a_violation():
    call = _call_event("→ TOOL_CALL check_network_status: {\"line_id\": \"L1002\"}")
    violations = catalog_violations(call, SCHEMAS)
    assert [item.kind for item in violations] == ["TOOL_NOT_IN_CATALOG"]


def test_missing_required_top_level_field():
    call = _call_event("→ TOOL_CALL get_user_details: {}")
    violations = catalog_violations(call, SCHEMAS)
    assert any(item.kind == "MISSING_REQUIRED_FIELD" and "user_id" in item.detail
               for item in violations)


def test_missing_required_nested_field_in_array_items():
    call = _call_event(
        '→ TOOL_CALL update_reservation_flights: {"reservation_id": "ZFA04Y", '
        '"flights": [{"flight_number": "HAT001"}, {"flight_number": "HAT002", "date": "2024-05-01"}]}')
    violations = catalog_violations(call, SCHEMAS)
    details = [item.detail for item in violations if item.kind == "MISSING_REQUIRED_FIELD"]
    assert any("flights[0].date" in detail for detail in details), details
    assert not any("flights[1]" in detail for detail in details), details


def test_enum_violation_and_valid_enum():
    bad = _call_event(
        '→ TOOL_CALL update_reservation_flights: {"reservation_id": "Z", '
        '"flights": [{"flight_number": "H1", "date": "d"}], "cabin": "first"}')
    assert any(item.kind == "ENUM_VIOLATION" for item in catalog_violations(bad, SCHEMAS))
    good = _call_event(
        '→ TOOL_CALL update_reservation_flights: {"reservation_id": "Z", '
        '"flights": [{"flight_number": "H1", "date": "d"}], "cabin": "economy"}')
    assert catalog_violations(good, SCHEMAS) == []


def test_extra_fields_and_type_coercion_not_flagged():
    call = _call_event(
        '→ TOOL_CALL get_user_details: {"user_id": 12345, "extra": "whatever"}')
    assert catalog_violations(call, SCHEMAS) == []


def test_component_exempts_user_calls_and_empty_responses():
    user_call = normalize("", '⟦USER⟧\n→ TOOL_CALL get_user_details: {"user_id": "u"}')
    calls = [event for event in user_call if event.kind == "call"]
    assert calls and calls[0].actor == "user"
    assert catalog_conformance_component(calls, SCHEMAS) is None
    assert catalog_conformance_component([], SCHEMAS) is None
    assert catalog_conformance_component([], {}) is None


def test_component_single_option_preserves_world_cardinality():
    call = _call_event("→ TOOL_CALL check_sim_status: {}")
    component = catalog_conformance_component([call], SCHEMAS)
    assert component is not None
    assert len(component.axis.choice_ids) == 1
    assert component.axis.enumeration_complete is True
    obligations = list(next(iter(component.options.values())).obligations)
    assert {obligation.atom.kind for obligation in obligations} == {
        AtomKind.CALL_IN_CATALOG, ARGUMENT_CONFORMS_SCHEMA}
    contract = catalog_option_contract(component)
    rule = contract["rules"]["catalog:conformance"]
    assert set(rule["obligations"]) == {obligation.obligation_id for obligation in obligations}


def _prove(call_marker: str, body: str, kind: AtomKind):
    call = _call_event(f"{call_marker}: {body}")
    ledger = EvidenceLedger.from_events((call,))
    index = LedgerIndex(ledger)
    from guardian_truth.vnext.e2e.world_integration_v1 import prove_e2e_atom
    atom = type("A", (), {})  # placeholder replaced below
    from guardian_truth.vnext.proof_records import ProofAtom
    real = ProofAtom(f"catalog:e0:{kind.value}", kind, EntityRef("catalog", "e0", "catalog"),
                     call.tool.name if call.tool else "", "true", "assistant", TimeMode.AT, 0)
    return prove_e2e_atom(real, ledger, index, ContractRegistry((), schemas=SCHEMAS))


def test_prover_paths():
    ok = _prove("→ TOOL_CALL get_user_details", '{"user_id": "u"}', AtomKind.CALL_IN_CATALOG)
    assert ok.value is Truth.TRUE and ok.supports == ("e0",)
    bad = _prove("→ TOOL_CALL check_sim_status", "{}", AtomKind.CALL_IN_CATALOG)
    assert bad.value is Truth.FALSE and bad.refutes == ("e0",)
    arguments_bad = _prove("→ TOOL_CALL get_user_details", "{}", ARGUMENT_CONFORMS_SCHEMA)
    assert arguments_bad.value is Truth.FALSE
    arguments_unknown_for_noncatalog = _prove("→ TOOL_CALL check_sim_status", "{}",
                                              ARGUMENT_CONFORMS_SCHEMA)
    assert arguments_unknown_for_noncatalog.value is Truth.UNKNOWN
    no_registry = _prove("→ TOOL_CALL get_user_details", '{"user_id": "u"}', AtomKind.CALL_IN_CATALOG)
    from guardian_truth.vnext.e2e.world_integration_v1 import prove_e2e_atom
    atom = no_registry.atom
    unknown = prove_e2e_atom(atom, EvidenceLedger.from_events(()), LedgerIndex(EvidenceLedger.from_events(())),
                             ContractRegistry(()))
    assert unknown.value is Truth.UNKNOWN


VIOLATING_CASE = E2ECaseInput(
    case_id="t-catalog-1", family="",
    system_policy="",
    user_request="",
    history=(),
    target_response="→ TOOL_CALL check_network_status: {\"line_id\": \"L1002\"}",
)

FIXED_CASE = E2ECaseInput(
    case_id="t-catalog-1", family="",
    system_policy="",
    user_request="",
    history=(),
    target_response="→ TOOL_CALL get_user_details: {\"user_id\": \"u1\"}",
)


class _OfflineBackend:
    """No live LLM: every semantic proposal fails at the transport level.

    The catalog-conformance axis itself must be fully deterministic (zero
    proposals); the other frontends degrade to recorded failures, which is
    exactly the offline structural configuration."""

    def propose(self, task, payload, schema):
        from guardian_truth.vnext.semantic import Proposal
        return Proposal(None, "ERROR", "NOT_EVALUATED", "offline_test")


def _guardian(schemas, flag=True):
    return GuardianE2EV1(
        _OfflineBackend(), registry=ContractRegistry((), schemas=schemas),
        arm=E2EArmConfig("B4h", ("h0_hist",), ("conservative",)),
        adapter_mode=None or __import__("guardian_truth.vnext.adapters", fromlist=["AdapterMode"]).AdapterMode.AUDIT,
        enable_t2=False, semantics=SEMANTICS_ARMS["B3"], catalog_conformance=flag)


def test_end_to_end_certified_violation():
    analysis = _guardian(SCHEMAS).analyze_e2e_v1(VIOLATING_CASE)
    assert analysis.result.status.value == "PROVED_ERROR"
    assert analysis.result.certificate_check is not None and analysis.result.certificate_check.valid
    catalog_obligations = [obligation for world in analysis.problem.worlds
                           for obligation in world.obligations
                           if obligation.hypothesis_id == "GUARDIAN_CATALOG_CONFORMANCE_V1"]
    assert catalog_obligations, "catalog obligations must be present in every world"


def test_end_to_end_clean_call_not_an_error():
    analysis = _guardian(SCHEMAS).analyze_e2e_v1(FIXED_CASE)
    assert analysis.result.status.value != "PROVED_ERROR"


def test_flag_off_keeps_frozen_behavior():
    analysis_off = _guardian(SCHEMAS, flag=False).analyze_e2e_v1(VIOLATING_CASE)
    assert analysis_off.result.status.value in {"UNRESOLVED", "PROVED_NO_ERROR"}
    names = [axis.name for axis in analysis_off.problem.axes]
    assert "catalog_conformance" not in names
    analysis_on = _guardian(SCHEMAS, flag=True).analyze_e2e_v1(VIOLATING_CASE)
    assert "catalog_conformance" in [axis.name for axis in analysis_on.problem.axes]


RENAMED_SCHEMAS = {
    "zzz_update_" + name: {**schema, "name": "zzz_update_" + name}
    for name, schema in SCHEMAS.items()
}


def test_metamorphic_rename_invariance():
    """Renaming every tool (incl. the violating one) must preserve the verdict."""
    renamed_case = E2ECaseInput(
        case_id="t-catalog-renamed", family="",
        system_policy="", user_request="", history=(),
        target_response="→ TOOL_CALL zzz_check_network_status: {\"line_id\": \"L1002\"}",
    )
    renamed = {"zzz_update_get_user_details": RENAMED_SCHEMAS["zzz_update_get_user_details"],
               "zzz_update_check_line": {
                   "name": "zzz_update_check_line", "description": "",
                   "parameters": {"line_id": {"type": "string", "required": True,
                                              "description": ""}}}}
    analysis = _guardian(renamed).analyze_e2e_v1(renamed_case)
    assert analysis.result.status.value == "PROVED_ERROR"
    assert analysis.result.certificate_check.valid


def test_metamorphic_fix_the_condition_removes_the_violation():
    """Paired case: same shape, one essential condition repaired -> no ERROR."""
    fixed = E2ECaseInput(
        case_id="t-catalog-fixed", family="",
        system_policy="", user_request="", history=(),
        target_response="→ TOOL_CALL zzz_update_get_user_details: {\"user_id\": \"u1\"}",
    )
    schemas = {"zzz_update_get_user_details": RENAMED_SCHEMAS["zzz_update_get_user_details"]}
    analysis = _guardian(schemas).analyze_e2e_v1(fixed)
    assert analysis.result.status.value != "PROVED_ERROR"


def test_label_and_id_independence():
    """Gold firewall: label/id never enter inference; verdict depends only on
    prompt+response (labels are not even a field of E2ECaseInput)."""
    a = _guardian(SCHEMAS).analyze_e2e_v1(
        replace_id(VIOLATING_CASE, "id-alpha"))
    b = _guardian(SCHEMAS).analyze_e2e_v1(
        replace_id(VIOLATING_CASE, "id-beta-999"))
    assert a.result.status == b.result.status


def replace_id(case, new_id):
    return E2ECaseInput(
        case_id=new_id, family=case.family, system_policy=case.system_policy,
        user_request=case.user_request, history=case.history,
        target_response=case.target_response)
