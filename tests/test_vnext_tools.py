from dataclasses import replace
import json

import pytest

from guardian_truth.vnext.integrity import canonical
from guardian_truth.vnext.ledger import EvidenceLedger
from guardian_truth.vnext.normalize import normalize, tool_identity
from guardian_truth.vnext.semantic import Proposal
from guardian_truth.vnext.tools import (ConditionalGuarantee, ContractRegistry, EffectSpec,
    FieldCondition, TrustedContract, evaluate_t1, propose_t2)
from guardian_truth.vnext.types import EffectStatus, Reason


IDENTITY = tool_identity("fixture.archive", {"record_id": "string"}, provider="vnext-fixture", version="v1")


def condition(source, key, value):
    return FieldCondition(source, (key,), canonical(value).decode("utf-8"))


def contract():
    state = EffectSpec("record_id", "archived", "true")
    completed = replace(state, causal_action_confirmed=True)
    return TrustedContract(IDENTITY, (), ("record_id",), ("archived",),
        (ConditionalGuarantee((condition("result", "status", "completed"),), (completed,)),
         ConditionalGuarantee((condition("result", "status", "noop"), condition("prior_state", "archived", True)), (state,))),
        (), (condition("result", "status", "noop"), condition("prior_state", "archived", True)),
        "timeout/failure do not guarantee no effect", "event position only", "state idempotent, action count not idempotent",
        "benchmarks/vnext/tool_reference_v1.py",
        (ConditionalGuarantee((condition("result", "status", "partial"),), (state,)),
         ConditionalGuarantee((condition("result", "status", "accepted"),), (state,))))


def events(status="completed", *, identity=IDENTITY, result_payload=None):
    value = json.dumps(result_payload or {"status": status})
    text = '⟦ASSISTANT_TOOL_CALL name="fixture.archive" call_id="a"⟧\n{"record_id":"Q-101"}\n'
    text += '⟦TOOL_RESULT name="fixture.archive" requestor="assistant" call_id="a"⟧\n' + value
    return normalize(text, "", tool_identities=(identity,))


def test_exact_identity_and_conditional_completion_guarantee():
    call, result = events()
    answer = evaluate_t1(ContractRegistry((contract(),)), call, result)
    assert answer.status is EffectStatus.TRUSTED_EFFECT
    assert len(answer.effects) == 1
    assert answer.effects[0].causal_action_confirmed
    assert answer.effects[0].contract_sha256 == contract().sha256


def test_noop_requires_prior_state_and_does_not_prove_completed_mutation():
    call, result = events("noop")
    registry = ContractRegistry((contract(),))
    assert evaluate_t1(registry, call, result).status is EffectStatus.UNKNOWN_EFFECT
    answer = evaluate_t1(registry, call, result, prior_state={"archived": True})
    assert answer.no_effect_proved
    assert answer.status is EffectStatus.TRUSTED_EFFECT
    assert not answer.effects[0].causal_action_confirmed


@pytest.mark.parametrize("status", ["timeout", "failed", "error", "unknown"])
def test_failure_never_becomes_no_effect_without_contract_guarantee(status):
    call, result = events(status)
    answer = evaluate_t1(ContractRegistry((contract(),)), call, result)
    assert answer.status is EffectStatus.UNKNOWN_EFFECT
    assert not answer.no_effect_proved and answer.effects == ()


@pytest.mark.parametrize("status", ["partial", "accepted"])
def test_partial_or_accepted_does_not_become_completed(status):
    call, result = events(status)
    answer = evaluate_t1(ContractRegistry((contract(),)), call, result)
    assert answer.status is EffectStatus.POSSIBLE_EFFECT
    assert not answer.effects[0].causal_action_confirmed


@pytest.mark.parametrize("identity", [replace(IDENTITY, version="v2"), replace(IDENTITY, schema_sha256="b" * 64),
                                      replace(IDENTITY, provider="other-provider"), replace(IDENTITY, version=None)])
def test_same_name_cannot_transfer_contract_across_identity(identity):
    call, result = events(identity=identity)
    answer = evaluate_t1(ContractRegistry((contract(),)), call, result)
    assert answer.status is EffectStatus.UNKNOWN_EFFECT
    assert Reason.TOOL_VERSION_MISMATCH in answer.reasons


def test_result_pairing_mismatch_cannot_establish_effect():
    call, result = events()
    answer = evaluate_t1(ContractRegistry((contract(),)), call, replace(result, call_id="wrong"))
    assert answer.effects == ()


def test_trusted_contract_hash_includes_effect_semantics():
    original = contract()
    assert original.sha256 != replace(original, writes=("other_field",)).sha256


def test_registry_does_not_accept_t2_or_unversioned_tool_objects():
    with pytest.raises(TypeError):
        ContractRegistry(({"generated_contract": True},))
    with pytest.raises(ValueError):
        replace(contract(), identity=replace(IDENTITY, version=None))


class Backend:
    def __init__(self, hypotheses):
        self.hypotheses = hypotheses

    def propose(self, task, payload, schema):
        assert task == "tool_conditional_effect_hypotheses"
        return Proposal(json.dumps({"hypotheses": self.hypotheses}), "SUCCESS", "VALID")


def hypothesis(**changes):
    return dict(argument_entity_field="record_id", predicate="archived", value_json="true",
                result_grounding_fields=["status"], **changes)


def test_t2_grounded_effect_is_never_trusted_or_causal():
    call, result = events()
    answer = propose_t2(call, result, Backend([hypothesis()]), schema={"record_id": "string"})
    assert answer.status is EffectStatus.POSSIBLE_EFFECT
    assert answer.effects[0].contract_sha256 is None
    assert answer.effects[0].status is not EffectStatus.TRUSTED_EFFECT
    assert not answer.effects[0].causal_action_confirmed


def test_t2_explicit_guaranteed_effect_field_is_rejected():
    call, result = events()
    unsafe = hypothesis()
    unsafe["guaranteed_effect"] = True
    answer = propose_t2(call, result, Backend([unsafe]), schema={})
    assert answer.effects == ()
    assert Reason.SCHEMA_ERROR in answer.reasons


@pytest.mark.parametrize("change", [{"argument_entity_field": "invented_id"},
                                   {"result_grounding_fields": ["missing_field"]}, {"value_json": "NaN"}])
def test_t2_ungrounded_or_invalid_candidates_are_discarded_without_facts(change):
    call, result = events()
    item = hypothesis()
    item.update(change)
    answer = propose_t2(call, result, Backend([item]), schema={})
    assert answer.effects == ()
    assert answer.status is EffectStatus.UNKNOWN_EFFECT


def test_t2_distinct_effects_preserve_ambiguity():
    call, result = events()
    second = hypothesis()
    second["value_json"] = "false"
    answer = propose_t2(call, result, Backend([hypothesis(), second]), schema={})
    assert answer.status is EffectStatus.AMBIGUOUS_EFFECT
    assert len(answer.effects) == 2


def test_effects_ledger_retains_typed_possible_and_trusted_provenance():
    call, result = events()
    answer = evaluate_t1(ContractRegistry((contract(),)), call, result)
    ledger = replace(EvidenceLedger.from_events((call, result)), effects=answer.effects)
    assert ledger.effects_of(result.event_id) == answer.effects
    assert ledger.observations[0].predicate == "status"
