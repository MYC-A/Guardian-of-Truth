"""Unit tests for the Step 2 evidence module."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from guardian_truth.step2.arms import (apply_read_confirmation, arm_D_result_only,
                                       arm_F_structural, arm_G_extractive,
                                       arm_I_contract, build_ledger, run_arm)
from guardian_truth.step2.ledger import FactLedger, Proposition
from guardian_truth.step2.result_types import classify_payload, json_path_get
from guardian_truth.step2.types import (EffectStrength, FactEvent, LedgerKind,
                                        Provenance, Truth, WorldFact, Authority)
from guardian_truth.step2.verifier import (CallEvent, CandidateFact, ResultEvent,
                                           TrajectoryCase, verify_candidate)


# ------------------------------------------------------------ result taxonomy

def test_result_taxonomy():
    assert classify_payload({"success": True}) .value == "SUCCESS_ACK"
    assert classify_payload({"error": "boom"}).value == "FAILURE"
    assert classify_payload({"success": False}).value == "FAILURE"
    assert classify_payload({"status": "queued"}).value == "ASYNC_ACCEPTED"
    assert classify_payload({"status": "cancelled", "order_id": "A"}).value == "BUSINESS_STATE"
    assert classify_payload({"user_id": "u1", "name": {"first": "A"}}).value == "OBSERVATION"
    assert classify_payload({}).value == "EMPTY"
    assert classify_payload("not-a-dict") .value == "MALFORMED"
    assert classify_payload(None).value == "EMPTY"


def test_json_path():
    payload = {"a": {"b": [{"c": 5}]}, "status": "ok"}
    assert json_path_get(payload, "$.status") == ("ok", True)
    assert json_path_get(payload, "$.a.b[0].c") == (5, True)
    assert json_path_get(payload, "$.a.x") == (None, False)


# ------------------------------------------------------------------- lattice

def test_strength_lattice():
    assert EffectStrength.REQUESTED < EffectStrength.EXECUTED
    assert EffectStrength.EXECUTED.at_least(EffectStrength.REQUESTED)
    assert not EffectStrength.REQUESTED.at_least(EffectStrength.EXECUTED)
    try:
        EffectStrength.OBSERVED < EffectStrength.EXECUTED
        raise AssertionError("OBSERVED must not compare with mutation axis")
    except TypeError:
        pass


# -------------------------------------------------------------------- ledger

def _fact(pred="order.status", etype="order", eid="A", value='"cancelled"',
          strength=EffectStrength.OBSERVED, index=1):
    return WorldFact(predicate=pred, entity_type=etype, entity_id=eid,
                     value=value, truth=Truth.TRUE, strength=strength,
                     authority=Authority.READ_OBSERVATION,
                     provenance=Provenance(call_id="c1", result_index=index,
                                           json_path="$.status"),
                     observed_at=index, valid_from=index)


def test_ledger_latest_and_prior_true():
    ledger = FactLedger()
    ledger.append(FactEvent(index=1, kind=LedgerKind.OBSERVE, fact=_fact(value='"pending"', index=1)))
    ledger.append(FactEvent(index=3, kind=LedgerKind.OBSERVE, fact=_fact(value='"cancelled"', index=3)))
    latest = ledger.latest("order", "A", "order.status")
    assert latest.value == '"cancelled"' and latest.observed_at == 3
    assert latest.conflicted_history is True
    before = ledger.prior_true("order", "A", "order.status", '"pending"', before=2)
    assert before.truth is Truth.TRUE
    missing = ledger.prior_true("order", "A", "order.status", '"cancelled"', before=2)
    assert missing.truth is Truth.UNKNOWN  # absence of evidence, never FALSE


def test_ledger_as_of():
    ledger = FactLedger()
    ledger.append(FactEvent(index=1, kind=LedgerKind.OBSERVE, fact=_fact(value='"pending"', index=1)))
    ledger.append(FactEvent(index=3, kind=LedgerKind.OBSERVE, fact=_fact(value='"cancelled"', index=3)))
    v2 = ledger.latest("order", "A", "order.status", as_of=2)
    assert v2.value == '"pending"'  # no retroactive justification


# ------------------------------------------------------------------ witness

def _case():
    return TrajectoryCase(
        case_id="t", category="t", domain="t",
        tools=({"name": "cancel_order", "description": "Cancel the whole order.",
                "fields": {"order_id": {"type": "string", "required": True}}},),
        calls=(CallEvent(index=0, call_id="c1", tool="cancel_order",
                         payload={"order_id": "#1"}),),
        results=(ResultEvent(index=1, call_id="c1", tool="cancel_order",
                             payload={"order_id": "#1", "status": "cancelled"}),))


def test_witness_accepts_grounded_fact():
    case = _case()
    candidate = CandidateFact(predicate="order.status", entity_type="order",
                              entity_field="order_id", entity_value="#1",
                              value_json='"cancelled"', json_path="$.status",
                              strength=EffectStrength.EXECUTED)
    verdict = verify_candidate(case, case.calls[0], case.results[0], candidate)
    assert verdict.witness_checks == ("paired", "decoded", "path_present",
                                      "value_equal", "entity_bound", "strength_witnessed")


def test_witness_rejects_generic_success_overclaim():
    case = _case()
    case = TrajectoryCase(case_id="t", category="t", domain="t", tools=case.tools,
                          calls=case.calls,
                          results=(ResultEvent(index=1, call_id="c1", tool="cancel_order",
                                               payload={"success": True}),))
    candidate = CandidateFact(predicate="order.status", entity_type="order",
                              entity_field="order_id", entity_value="#1",
                              value_json='"cancelled"', json_path="$.status",
                              strength=EffectStrength.EXECUTED)
    verdict = verify_candidate(case, case.calls[0], case.results[0], candidate)
    assert getattr(verdict, "code", None) in ("PATH_MISSING", "STRENGTH_UNWITNESSED")


def test_witness_rejects_wrong_entity():
    case = _case()
    candidate = CandidateFact(predicate="order.status", entity_type="order",
                              entity_field="order_id", entity_value="#2",
                              value_json='"cancelled"', json_path="$.status",
                              strength=EffectStrength.EXECUTED)
    verdict = verify_candidate(case, case.calls[0], case.results[0], candidate)
    assert getattr(verdict, "code", None) == "ENTITY_MISMATCH"


def test_witness_rejects_async_as_executed():
    case = TrajectoryCase(
        case_id="t", category="t", domain="t",
        tools=({"name": "dispatch", "description": "Dispatch.", "fields": {}},),
        calls=(CallEvent(index=0, call_id="c1", tool="dispatch", payload={"parcel_id": "P1"}),),
        results=(ResultEvent(index=1, call_id="c1", tool="dispatch",
                             payload={"parcel_id": "P1", "status": "queued"}),))
    candidate = CandidateFact(predicate="parcel.status", entity_type="parcel",
                              entity_field="parcel_id", entity_value="P1",
                              value_json='"dispatched"', json_path="$.status",
                              strength=EffectStrength.EXECUTED)
    verdict = verify_candidate(case, case.calls[0], case.results[0], candidate)
    assert getattr(verdict, "code", None) == "VALUE_MISMATCH"
    candidate2 = CandidateFact(predicate="parcel.status", entity_type="parcel",
                               entity_field="parcel_id", entity_value="P1",
                               value_json='"queued"', json_path="$.status",
                               strength=EffectStrength.EXECUTED)
    verdict2 = verify_candidate(case, case.calls[0], case.results[0], candidate2)
    assert getattr(verdict2, "code", None) == "STRENGTH_UNWITNESSED"


# --------------------------------------------------------------------- arms

def test_arm_D_reads_only():
    case = _case()
    out = arm_D_result_only(case)
    # BUSINESS_STATE result: D only reads OBSERVATION-shaped results -> silent
    assert out.verified == [] and out.ungrounded == []


def test_arm_F_classifies_business_state():
    case = _case()
    out = arm_F_structural(case)
    assert len(out.verified) == 1
    fact = out.verified[0].fact
    assert fact.value == '"cancelled"' and fact.strength is EffectStrength.EXECUTED


def test_arm_F_generic_success_proves_nothing():
    case = TrajectoryCase(
        case_id="t", category="t", domain="t",
        tools=({"name": "cancel_order", "description": "Cancel.", "fields": {}},),
        calls=(CallEvent(index=0, call_id="c1", tool="cancel_order",
                         payload={"order_id": "#1"}),),
        results=(ResultEvent(index=1, call_id="c1", tool="cancel_order",
                             payload={"success": True}),))
    out = arm_F_structural(case)
    assert out.verified == []  # generic success: honest silence


def test_arm_G_conservative_on_mutations():
    case = _case()
    out = arm_G_extractive(case)
    assert len(out.verified) == 1  # status field is extractive post-state


def test_arm_I_contract_requires_binding():
    case = TrajectoryCase(
        case_id="t", category="t", domain="t",
        tools=({"name": "cancel_order", "description": "Cancel.", "fields": {}},),
        calls=(CallEvent(index=0, call_id="c1", tool="cancel_order",
                         payload={"order_id": "#1"}),),
        results=(ResultEvent(index=1, call_id="c1", tool="cancel_order",
                             payload={"order_id": "#1", "status": "cancelled"}),),
        oracle_contracts={"cancel_order": {
            "effect_class": "UPDATE", "entity_field": "order_id", "entity_type": "order",
            "result_bindings": {"order_id": "$.order_id"},
            "documented_contract": True,
            "postconditions": [
                {"predicate": "order.status", "json_path": "$.status",
                 "value_json": '"cancelled"', "strength": "EXECUTED"}]}})
    out = arm_I_contract(case)
    assert len(out.verified) == 1
    assert out.verified[0].fact.strength is EffectStrength.EXECUTED
    assert out.verified[0].fact.authority.value == "CONTRACT_GUARANTEE"


def test_arm_I_no_contract_means_unknown():
    out = arm_I_contract(_case())  # no contracts attached
    assert out.verified == []


# ------------------------------------------------------------------- J layer

def test_j_layer_confirms_and_contradicts():
    # mutation self-report + later confirming read
    ledger = FactLedger()
    ledger.append(FactEvent(index=1, kind=LedgerKind.EFFECT, fact=_fact(
        value='"cancelled"', strength=EffectStrength.EXECUTED, index=1)))
    ledger.append(FactEvent(index=3, kind=LedgerKind.OBSERVE, fact=_fact(
        value='"cancelled"', strength=EffectStrength.OBSERVED, index=3)))
    upgraded, ups = apply_read_confirmation(ledger)
    kinds = [e.fact.strength for e in upgraded.events]
    assert EffectStrength.CONFIRMED in kinds
    assert any(u["kind"] == "CONFIRMED" for u in ups)
    # contradiction: read says pending
    ledger2 = FactLedger()
    ledger2.append(FactEvent(index=1, kind=LedgerKind.EFFECT, fact=_fact(
        value='"cancelled"', strength=EffectStrength.EXECUTED, index=1)))
    ledger2.append(FactEvent(index=3, kind=LedgerKind.OBSERVE, fact=_fact(
        value='"pending"', strength=EffectStrength.OBSERVED, index=3)))
    fixed, ups2 = apply_read_confirmation(ledger2)
    assert any(u["kind"] == "CONTRADICTED" for u in ups2)
    latest = fixed.latest("order", "A", "order.status")
    assert latest.value == '"pending"'  # the read wins
    invalidated = [e for e in fixed.events if e.fact.invalidated_at == 3
                   and e.fact.value == '"cancelled"']
    assert invalidated, "self-report must carry invalidated_at"


# ---------------------------------------------------------------- claim probe

def test_claim_probe_support_status():
    ledger = FactLedger()
    ledger.append(FactEvent(index=1, kind=LedgerKind.OBSERVE, fact=_fact(
        value='"cancelled"', strength=EffectStrength.OBSERVED, index=1)))
    a1 = ledger.probe(Proposition("order", "A", "order.status", '"cancelled"'))
    assert a1.support.value == "SUPPORTED"
    a2 = ledger.probe(Proposition("order", "A", "order.status", '"pending"'))
    assert a2.support.value == "CONTRADICTED"
    a3 = ledger.probe(Proposition("order", "B", "order.status", '"cancelled"'))
    assert a3.support.value == "UNSUPPORTED"
    a4 = ledger.probe(Proposition("order", "A", "order.other"))
    assert a4.support.value == "UNSUPPORTED"


def test_claim_probe_pending_for_request_strength():
    ledger = FactLedger()
    ledger.append(FactEvent(index=1, kind=LedgerKind.EFFECT, fact=_fact(
        value='"created"', strength=EffectStrength.REQUESTED, index=1)))
    a = ledger.probe(Proposition("order", "A", "order.status", '"created"'))
    assert a.support.value == "PENDING"
