from dataclasses import replace

import pytest

from guardian_truth.vnext.adapters import AdapterMode, adapt
from guardian_truth.vnext.decision import CertifiedCoreResult, decide
from guardian_truth.vnext.escalation import (EscalationState, EscalationStep, escalate)
from guardian_truth.vnext.types import CoreStatus, Diagnostics, Reason
from test_vnext_proofs import REGISTRY, certified, context, problem, trajectory


@pytest.mark.parametrize("must,status", [(False, CoreStatus.PROVED_ERROR), (True, CoreStatus.PROVED_NO_ERROR)])
def test_definitive_core_is_certificate_gated(must, status):
    _, ctx, task, ledger = certified(must=must)
    result = decide(task, ledger, REGISTRY, context=ctx)
    assert result.status is status
    assert result.certificate_check.valid
    assert result.diagnostics.primary_reason is None


def test_failed_safety_certificate_downgrades_before_adapter():
    _, ctx, task, ledger = certified(must=True, complete=False)
    result = decide(task, ledger, REGISTRY, context=ctx)
    assert result.status is CoreStatus.UNRESOLVED
    assert result.certificate is None
    assert not result.certificate_check.valid
    assert "COMPLETENESS_UNPROVED" in result.diagnostics.missing_evidence
    assert adapt(result).binary_label is None


def test_cannot_construct_definitive_core_without_valid_certificate():
    with pytest.raises(ValueError):
        CertifiedCoreResult(CoreStatus.PROVED_ERROR, (), None, None, Diagnostics(None))


@pytest.mark.parametrize("status", [CoreStatus.UNRESOLVED, CoreStatus.INCONSISTENT])
def test_product_fallback_is_explicit_and_preserves_core_status(status):
    result = CertifiedCoreResult(status, (), None, None, Diagnostics(Reason.EVIDENCE_INCOMPLETE))
    assert adapt(result, mode=AdapterMode.AUDIT).binary_label is None
    assert adapt(result, mode=AdapterMode.SAFETY_FIRST).binary_label == 1
    competition = adapt(result, mode=AdapterMode.COMPETITION)
    assert competition.binary_label == int(status is CoreStatus.INCONSISTENT)
    assert competition.core_status is status and competition.used_fallback


def unresolved_state():
    prompt, response, ledger = trajectory("timeout")
    ctx = context(prompt, response)
    task = problem()
    return EscalationState(task, ledger, REGISTRY, ctx, decide(task, ledger, REGISTRY, context=ctx))


def test_bounded_escalation_runs_steps_once_then_terminal_unresolved():
    state = unresolved_state()
    calls = []
    callbacks = {step: lambda current, step=step: (calls.append(step), None)[1] for step in EscalationStep}
    outcome = escalate(state, callbacks)
    assert calls == list(EscalationStep)
    assert outcome.terminal_unresolved
    assert outcome.state.result.status is CoreStatus.UNRESOLVED
    assert outcome.state.result.diagnostics.attempted_escalations == tuple(step.value for step in EscalationStep)


def test_escalation_never_runs_after_definitive_verdict():
    _, ctx, task, ledger = certified()
    result = decide(task, ledger, REGISTRY, context=ctx)
    state = EscalationState(task, ledger, REGISTRY, ctx, result)
    assert escalate(state, {EscalationStep.NARROW_REPARSE: lambda _: pytest.fail("unexpected escalation")}).attempts == ()


def test_escalation_rejects_fact_rewrite_even_if_it_would_get_desired_answer():
    initial = unresolved_state()
    def rewrite(state):
        prompt, response, ledger = trajectory("completed")
        return replace(state, ledger=ledger, context=context(prompt, response))
    with pytest.raises(ValueError, match="rewrite"):
        escalate(initial, {EscalationStep.NARROW_REPARSE: rewrite})


def test_escalation_does_not_drop_admissible_interpretation():
    initial = unresolved_state()
    def prune(state):
        axis = replace(state.problem.axes[0], choice_ids=("preferred",))
        return replace(state, problem=replace(state.problem, axes=(axis,)))
    with pytest.raises(ValueError, match="discard"):
        escalate(initial, {EscalationStep.INDEPENDENT_CHALLENGER: prune})


def test_transport_schema_semantic_reasons_remain_separate():
    state = unresolved_state()
    result = decide(state.problem, state.ledger, state.registry, context=state.context,
                    semantic_reasons=(Reason.TRANSPORT_ERROR, Reason.SCHEMA_ERROR, Reason.CLAIM_UNTYPED))
    assert result.diagnostics.primary_reason is Reason.TRANSPORT_ERROR
    assert Reason.SCHEMA_ERROR in result.diagnostics.contributing_reasons
    assert result.diagnostics.blocked_claims == ("s0",)


def test_zero_escalation_budget_is_terminal_without_queries():
    result = escalate(unresolved_state(), {}, max_steps=0)
    assert result.terminal_unresolved and result.attempts == ()


def test_escalation_cannot_hide_semantic_rewrite_behind_same_hypothesis_id():
    initial = unresolved_state()
    def rewrite(state):
        hypothesis = replace(state.context.hypotheses[0], behavioral_relation="PROHIBITION")
        return replace(state, context=replace(state.context, hypotheses=(hypothesis,)))
    with pytest.raises(ValueError, match="reading"):
        escalate(initial, {EscalationStep.INDEPENDENT_CHALLENGER: rewrite})
