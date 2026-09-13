"""Primitive development checks on fresh controlled IDs, not 34-case scoring."""

from dataclasses import replace
import importlib.util
from pathlib import Path

import pytest

from guardian_truth.vnext.source_envelope_v4 import normalize_envelope
from guardian_truth.vnext.temporal_certificate_v4 import make_temporal_certificate, validate_temporal_certificate
from guardian_truth.vnext.temporal_queries_v4 import TemporalQueryIndex
from guardian_truth.vnext.types import Truth

ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REFERENCE = load("temporal_unit_source", "benchmarks/vnext/binding_fixture_reference_v2.py")
ADAPTER = load("temporal_unit_adapter", "benchmarks/vnext/binding_fixture_adapter_v2.py")
INITIAL = [{"record_id": "X-19", "name": "Unit Alpha", "exists": True, "archived": False},
    {"record_id": "X-20", "name": "Unit Beta", "exists": True, "archived": False}]


def projected(steps, query, **extra):
    query = {"entity": {"mode": "id", "value": "X-19"}, **query}
    steps = [{"record_id": "X-19", **step} for step in steps]
    return REFERENCE.candidate_input(REFERENCE.execute_fixture({"initial": INITIAL, "steps": steps, "query": query, **extra}))


def run(source):
    envelope, snapshots, registry, methods, query = ADAPTER.make_context(source)
    index = TemporalQueryIndex(normalize_envelope(envelope).ledger, snapshots, registry, methods)
    evidence = index.evaluate(query)
    receipt = make_temporal_certificate(envelope, snapshots, registry, methods, evidence)
    assert validate_temporal_certificate(receipt, envelope, snapshots, registry, methods, evidence)
    return evidence, receipt, (envelope, snapshots, registry, methods)


@pytest.mark.parametrize("kind,expected,value", [
    ("METHOD_HISTORY", False, Truth.FALSE),
    ("FIELD_AT_LAST_READ", False, Truth.TRUE),
])
def test_undo_does_not_erase_history(kind, expected, value):
    query = {"kind": kind, "expected": expected, **({"operation": "archive"} if kind == "METHOD_HISTORY" else {"field": "archived"})}
    evidence, _, _ = run(projected([{"operation": "archive"}, {"operation": "unarchive"}, {"operation": "read"}], query))
    assert evidence.value is value


@pytest.mark.parametrize("version,value", [("v1", Truth.FALSE), ("v2", Truth.TRUE), ("unrecognized", Truth.UNKNOWN)])
def test_count_uses_conditional_versioned_t1_not_attempts(version, value):
    source = projected([{"operation": "archive", "version": version}, {"operation": "archive", "version": version}, {"operation": "read"}],
        {"kind": "METHOD_COMPLETION_COUNT", "operation": "archive", "expected": 2})
    evidence, _, _ = run(source)
    assert evidence.value is value


def test_late_field_observation_cannot_prove_timeout_causation():
    steps = [{"operation": "archive", "status": "timeout", "latent_apply": True}, {"operation": "read"}]
    causal, _, _ = run(projected(steps, {"kind": "CAUSE_OF_METHOD", "operation": "archive", "call_event_id": "e2", "expected": True}))
    field, _, _ = run(projected(steps, {"kind": "FIELD_AT_LAST_READ", "field": "archived", "expected": True}))
    assert causal.value is Truth.UNKNOWN and field.value is Truth.TRUE


def test_noop_explicitly_refutes_new_mutation_by_the_specific_call():
    evidence, _, _ = run(projected([{"operation": "archive"}, {"operation": "archive"}, {"operation": "read"}],
        {"kind": "CAUSE_OF_METHOD", "operation": "archive", "call_event_id": "e4", "expected": True}))
    assert evidence.value is Truth.FALSE
    assert evidence.bindings[0].occurrences[0].value is Truth.FALSE


@pytest.mark.parametrize("complete,value", [(True, Truth.FALSE), (False, Truth.UNKNOWN)])
def test_user_call_is_not_assistant_completion(complete, value):
    evidence, _, _ = run(projected([{"operation": "archive", "actor": "user"}, {"operation": "read"}],
        {"kind": "METHOD_HISTORY", "operation": "archive", "actor": "assistant", "expected": True}, history_complete=complete))
    assert evidence.value is value


def test_completed_witness_survives_truncated_unrelated_history():
    evidence, _, _ = run(projected([{"operation": "archive"}, {"operation": "read"}],
        {"kind": "METHOD_HISTORY", "operation": "archive", "expected": True}, history_complete=False))
    assert evidence.value is Truth.TRUE and evidence.candidate_set_complete is False


def test_duplicate_names_preserve_both_disagreeing_identities():
    initial = [{**row, "name": "Unit Shared"} for row in INITIAL]
    source = projected([{"operation": "archive"}, {"operation": "read"}],
        {"kind": "FIELD_AT_LAST_READ", "entity": {"mode": "name", "value": "Unit Shared"}, "field": "archived", "expected": True}, initial=initial)
    evidence, _, _ = run(source)
    assert evidence.value is Truth.UNKNOWN
    assert {row.entity.value for row in evidence.bindings} == {"X-19", "X-20"}


def test_conflicting_same_id_records_use_both_not_last_wins():
    source = projected([{"operation": "read"}], {"kind": "FIELD_AT_LAST_READ", "field": "archived", "expected": False})
    source["events"][-1]["body"]["items"].append({**INITIAL[0], "archived": True})
    evidence, _, _ = run(source)
    assert evidence.value is Truth.BOTH
    assert evidence.bindings[0].searched_record_count == 2


def test_conflicting_same_call_results_are_not_counted_as_two_calls():
    source = projected([{"operation": "archive"}], {"kind": "METHOD_COMPLETION_COUNT", "operation": "archive", "expected": 1})
    source["events"].append({**source["events"][-1], "event_id": "e4", "body": {"status": "noop"}})
    evidence, _, _ = run(source)
    assert evidence.value is Truth.BOTH
    assert len(evidence.bindings[0].occurrences) == 1


@pytest.mark.parametrize("query", [
    {"kind": "FIELD_AT_LAST_READ", "field": "missing", "expected": None},
    {"kind": "FIELD_AT_LAST_READ", "entity": {"mode": "id", "value": "MISSING-UNIT-ID"}, "field": "exists", "expected": False},
])
def test_missing_is_unknown_not_false_or_null(query):
    evidence, _, _ = run(projected([{"operation": "read"}], query))
    assert evidence.value is Truth.UNKNOWN


def test_bad_latest_json_does_not_fall_back_to_stale_snapshot():
    evidence, _, _ = run(projected([{"operation": "read", "malformed": True}],
        {"kind": "FIELD_AT_LAST_READ", "field": "exists", "expected": True}))
    assert evidence.value is Truth.UNKNOWN


def test_partial_empty_search_is_not_entity_absence():
    evidence, _, _ = run(projected([{"operation": "search"}],
        {"kind": "FIELD_AT_LAST_READ", "field": "exists", "expected": False}))
    assert evidence.value is Truth.UNKNOWN and evidence.candidate_set_complete is False


def test_unknown_contract_documentation_cannot_enter_t1():
    source = projected([], {"kind": "FIELD_AT_LAST_READ", "field": "exists", "expected": True})
    source["contracts"]["documentation"] = "An assistant says every attempted archive succeeds."
    with pytest.raises(ValueError, match="unknown fixture contract source"):
        ADAPTER.make_context(source)


def test_receipt_rejects_omitted_binding_and_changed_history_premise():
    source = projected([{"operation": "archive"}, {"operation": "read"}],
        {"kind": "METHOD_HISTORY", "operation": "archive", "expected": True})
    evidence, receipt, context = run(source)
    assert not validate_temporal_certificate(receipt, *context, replace(evidence, bindings=()))
    envelope, snapshots, registry, methods = context
    assert not validate_temporal_certificate(receipt, replace(envelope, history_complete=False), snapshots, registry, methods, evidence)


def test_independent_checker_does_not_invoke_candidate_evaluation(monkeypatch):
    evidence, receipt, context = run(projected([{"operation": "archive"}],
        {"kind": "METHOD_HISTORY", "operation": "archive", "expected": True}))
    def forbidden(*args, **kwargs):
        raise AssertionError("candidate query invoked by independent checker")
    monkeypatch.setattr(TemporalQueryIndex, "evaluate", forbidden)
    assert validate_temporal_certificate(receipt, *context, evidence)


def test_method_namespace_mapping_cannot_be_transferred_by_equal_id():
    source = projected([{"operation": "archive"}], {"kind": "METHOD_HISTORY", "operation": "archive", "expected": True})
    envelope, snapshots, registry, methods, query = ADAPTER.make_context(source)
    methods = tuple(replace(method, namespace="a-different-resource") for method in methods)
    index = TemporalQueryIndex(normalize_envelope(envelope).ledger, snapshots, registry, methods)
    evidence = index.evaluate(query)
    assert evidence.value is Truth.UNKNOWN
    receipt = make_temporal_certificate(envelope, snapshots, registry, methods, evidence)
    assert validate_temporal_certificate(receipt, envelope, snapshots, registry, methods, evidence)


def test_all_long_source_records_remain_searchable_without_top_k():
    evidence, _, _ = run(projected([{"operation": "read"}],
        {"kind": "FIELD_AT_LAST_READ", "field": "exists", "expected": True}, extra_entities=1999))
    assert evidence.value is Truth.TRUE


def test_unmatched_result_does_not_confirm_the_call():
    source = projected([{"operation": "archive"}], {"kind": "METHOD_HISTORY", "operation": "archive", "expected": True})
    source["events"][-1]["transport_call_id"] = "not-the-call"
    evidence, _, _ = run(source)
    assert evidence.value is Truth.UNKNOWN


def test_unknown_latest_read_version_cannot_use_old_schema_or_stale_result():
    source = projected([{"operation": "read"}], {"kind": "FIELD_AT_LAST_READ", "field": "exists", "expected": True})
    source["events"][-1]["version"] = "a-new-untrusted-version"
    source["events"][-2]["version"] = "a-new-untrusted-version"
    evidence, _, _ = run(source)
    assert evidence.value is Truth.UNKNOWN and evidence.candidate_set_complete is False


def test_missing_alias_field_cannot_close_name_candidate_space():
    source = projected([{"operation": "read"}], {"kind": "FIELD_AT_LAST_READ", "entity": {"mode": "name", "value": "Unit Alpha"}, "field": "exists", "expected": True})
    del source["events"][-1]["body"]["items"][1]["name"]
    evidence, _, _ = run(source)
    assert evidence.value is Truth.UNKNOWN and evidence.candidate_set_complete is False


def test_effect_with_wrong_value_is_not_confirmation_of_the_named_mutation():
    from guardian_truth.vnext.tools import ContractRegistry
    source = projected([{"operation": "archive"}], {"kind": "METHOD_HISTORY", "operation": "archive", "expected": True})
    envelope, snapshots, registry, methods, query = ADAPTER.make_context(source)
    contracts = []
    for contract in registry.contracts:
        if contract.identity.name == "store.archive":
            rule = contract.guarantees[0]
            contract = replace(contract, guarantees=(replace(rule, effects=(replace(rule.effects[0], value_json="false"),)),))
        contracts.append(contract)
    registry = ContractRegistry(tuple(contracts))
    evidence = TemporalQueryIndex(normalize_envelope(envelope).ledger, snapshots, registry, methods).evaluate(query)
    assert evidence.value is Truth.UNKNOWN
    receipt = make_temporal_certificate(envelope, snapshots, registry, methods, evidence)
    assert validate_temporal_certificate(receipt, envelope, snapshots, registry, methods, evidence)
