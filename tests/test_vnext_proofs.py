from dataclasses import replace
import itertools

import pytest

from guardian_truth.vnext.certificates import (AuthoritativeAxis, CertificateContext,
    check_certificate, completeness_assumptions)
from guardian_truth.vnext.fixture_contracts import archive_fixture_contract
from guardian_truth.vnext.integrity import digest
from guardian_truth.vnext.ledger import EvidenceLedger, LedgerIndex
from guardian_truth.vnext.normalize import normalize
from guardian_truth.vnext.proof_evidence import prove_atom
from guardian_truth.vnext.proof_records import (AbsenceScope, AtomKind, InterpretationAxis, Obligation,
    ProofAtom, ProofProblem, TimeMode, WorldPlan, conjunction, disjunction, negate)
from guardian_truth.vnext.solver import make_certificate, solve
from guardian_truth.vnext.tools import ContractRegistry, evaluate_t1
from guardian_truth.vnext.types import (ClaimKind, CoreStatus, Disposition, EntityRef,
    EvaluationHypothesis, Reason, Span, Truth, TypedClaim)


ENTITY = EntityRef("record_id", "Q-101")
CONTRACT = archive_fixture_contract()
REGISTRY = ContractRegistry((CONTRACT,))


def trajectory(status="completed", response="I archived Q-101.", *, actor="ASSISTANT", complete=True):
    prompt = f'⟦{actor}_TOOL_CALL name="fixture.archive" call_id="a"⟧\n{{"record_id":"Q-101"}}\n'
    prompt += f'⟦TOOL_RESULT name="fixture.archive" requestor="{actor.lower()}" call_id="a"⟧\n{{"status":"{status}"}}'
    events = normalize(prompt, response, tool_identities=(CONTRACT.identity,))
    ledger = EvidenceLedger.from_events(events, history_complete=complete,
                                       completeness_basis="controlled complete source trajectory" if complete else None)
    effects = evaluate_t1(REGISTRY, events[0], events[1]).effects
    return prompt, response, replace(ledger, effects=effects)


def atom(kind=AtomKind.ACTION_COMPLETED, **changes):
    value = ProofAtom("a0", kind, ENTITY, "fixture.archive", "true", "assistant", TimeMode.THROUGH, 2)
    return replace(value, **changes)


def problem(*, must=True, primitive=None, closed=True):
    axis = InterpretationAxis("policy", ("h0",), "fixture closed policy universe", closed)
    obligation = Obligation("o0", "h0", "s0", primitive or atom(), must)
    factual = Obligation("f0", "GUARDIAN_FACTUAL_CONSISTENCY_V1", "s0", primitive or atom(), True)
    return ProofProblem((axis,), (WorldPlan("w0", ("h0",), (factual, obligation)),))


def context(prompt, response, *, must=True):
    claim = TypedClaim("s0", Span("response", 0, len(response)), Disposition.VERIFIABLE_TYPED,
        ClaimKind.ACTION_COMPLETED, "assistant", "fixture.archive", "Q-101", ("Q-101",),
        "POSITIVE", "ASSERTED", "PAST", ("ASSISTANT",))
    hyp = EvaluationHypothesis("h0", "policy", "REQUIREMENT" if must else "PROHIBITION", "assistant",
        "fixture.archive", "Q-101", (), (), (Span("policy", 0, 7),))
    return CertificateContext(prompt, response, (CONTRACT.identity,), (claim,),
        (AuthoritativeAxis("policy", ("h0",), "fixture closed policy universe", "AUTHORITATIVE_CLOSED_UNIVERSE"),),
        (hyp,), "archive")


def certified(*, must=True, complete=True):
    prompt, response, ledger = trajectory(complete=complete)
    task = problem(must=must)
    ctx = context(prompt, response, must=must)
    result = solve(task, ledger, REGISTRY)
    certificate = make_certificate(result, task, ledger, REGISTRY, prompt=prompt, response=response,
        completeness_assumptions=completeness_assumptions(ctx, task, ledger), validation_context=ctx)
    return certificate, ctx, task, ledger


@pytest.mark.parametrize("value", list(Truth))
def test_four_value_logic_preserves_information(value):
    assert negate(negate(value)) is value
    assert conjunction((value, Truth.TRUE)) is value
    assert disjunction((value, Truth.FALSE)) is value
    assert conjunction(()) is Truth.TRUE
    assert disjunction(()) is Truth.FALSE


def test_completed_action_requires_verified_t1_effect():
    _, _, ledger = trajectory()
    proof = prove_atom(atom(), ledger, LedgerIndex(ledger), REGISTRY)
    assert proof.value is Truth.TRUE
    assert proof.supports == (ledger.effects[0].effect_id,)
    empty = replace(ledger, effects=())
    assert prove_atom(atom(), empty, LedgerIndex(empty), REGISTRY).value is Truth.UNKNOWN


@pytest.mark.parametrize("status", ["timeout", "failed", "accepted", "partial"])
def test_failed_or_attempted_call_is_not_completed_or_no_effect(status):
    _, _, ledger = trajectory(status)
    proof = prove_atom(atom(), ledger, LedgerIndex(ledger), REGISTRY)
    assert proof.value is Truth.UNKNOWN
    attempted = prove_atom(atom(AtomKind.CALL_ATTEMPTED), ledger, LedgerIndex(ledger), REGISTRY)
    assert attempted.value is Truth.TRUE


def test_user_action_is_not_assistant_action():
    _, _, ledger = trajectory(actor="USER")
    assert prove_atom(atom(), ledger, LedgerIndex(ledger), REGISTRY).value is Truth.UNKNOWN
    assert prove_atom(atom(actor="user"), ledger, LedgerIndex(ledger), REGISTRY).value is Truth.TRUE


def test_forged_trusted_effect_fails_independent_regeneration():
    _, _, ledger = trajectory()
    forged = replace(ledger.effects[0], value_json="false")
    ledger = replace(ledger, effects=(forged,))
    assert prove_atom(atom(), ledger, LedgerIndex(ledger), REGISTRY).value is Truth.UNKNOWN


def test_matching_state_does_not_prove_causality_without_unique_call_and_target_effect():
    _, _, ledger = trajectory()
    ambiguous = atom(AtomKind.CAUSAL_ATTRIBUTION)
    assert prove_atom(ambiguous, ledger, LedgerIndex(ledger), REGISTRY).value is Truth.UNKNOWN
    exact = replace(ambiguous, call_id=ledger.events[0].call_id, effect_predicate="archived", effect_expected_json="true")
    assert prove_atom(exact, ledger, LedgerIndex(ledger), REGISTRY).value is Truth.TRUE
    wrong = replace(exact, effect_predicate="deleted")
    assert prove_atom(wrong, ledger, LedgerIndex(ledger), REGISTRY).value is Truth.UNKNOWN


def test_timeout_late_get_supports_state_not_restore_causality():
    prompt, response, _ = trajectory("timeout")
    prompt += '\n⟦TOOL_RESULT name="GET" requestor="assistant"⟧\n{"record_id":"Q-101","exists":true}'
    ledger = EvidenceLedger.from_events(normalize(prompt, response, tool_identities=(CONTRACT.identity,)))
    state = atom(AtomKind.OBSERVED_STATE, predicate="exists", actor=None, time_mode=TimeMode.AT, time_index=2)
    assert prove_atom(state, ledger, LedgerIndex(ledger), REGISTRY).value is Truth.TRUE
    causal = atom(AtomKind.CAUSAL_ATTRIBUTION, time_index=3, call_id="call:e0", effect_predicate="exists", effect_expected_json="true")
    proof = prove_atom(causal, ledger, LedgerIndex(ledger), REGISTRY)
    assert proof.value is Truth.UNKNOWN and Reason.CAUSALITY_UNPROVED in proof.reasons


def test_historical_action_does_not_disappear_after_later_state_change():
    prompt, response, ledger = trajectory()
    prompt += '\n⟦TOOL_RESULT name="GET" requestor="assistant"⟧\n{"record_id":"Q-101","archived":false}'
    events = normalize(prompt, response, tool_identities=(CONTRACT.identity,))
    value = replace(EvidenceLedger.from_events(events), effects=ledger.effects)
    never = atom(AtomKind.HISTORICAL_ACTION, expected_json="false", time_index=3)
    assert prove_atom(never, value, LedgerIndex(value), REGISTRY).value is Truth.FALSE
    state = atom(AtomKind.OBSERVED_STATE, predicate="archived", actor=None, time_mode=TimeMode.AT, time_index=2)
    assert prove_atom(state, value, LedgerIndex(value), REGISTRY).value is Truth.FALSE


def test_past_observation_is_not_automatically_current_state():
    prompt = '⟦TOOL_RESULT name="GET" requestor="assistant"⟧\n{"record_id":"Q-101","exists":true}'
    ledger = EvidenceLedger.from_events(normalize(prompt, "It exists now."))
    state = atom(AtomKind.OBSERVED_STATE, predicate="exists", actor=None, time_mode=TimeMode.AT, time_index=1)
    assert prove_atom(state, ledger, LedgerIndex(ledger), REGISTRY).value is Truth.UNKNOWN
    assert prove_atom(replace(state, time_mode=TimeMode.LATEST_OBSERVATION), ledger, LedgerIndex(ledger), REGISTRY).value is Truth.TRUE


def test_failed_call_and_empty_retrieval_do_not_prove_absence():
    _, _, ledger = trajectory("failed")
    negative = atom(AtomKind.HISTORICAL_ACTION, expected_json="false")
    scope = AbsenceScope("s", ENTITY, "fixture.archive", "assistant", 2, "explicit fixture closed action ontology", ("fixture.archive",))
    proof = prove_atom(negative, ledger, LedgerIndex(ledger), REGISTRY, (scope,))
    assert proof.value is Truth.UNKNOWN and proof.absence_scope_id is None


def test_solver_disagreement_is_not_majority_or_any_error():
    _, _, ledger = trajectory()
    axes = (InterpretationAxis("policy", tuple(f"h{i}" for i in range(10)), "fixture closed policy", True),)
    worlds = tuple(WorldPlan(f"w{i}", (f"h{i}",), (Obligation(f"o{i}", f"h{i}", "s0", atom(), i == 9),)) for i in range(10))
    assert solve(ProofProblem(axes, worlds), ledger, REGISTRY).status is CoreStatus.UNRESOLVED


def test_all_policy_goal_binding_effect_combinations_are_required():
    _, _, ledger = trajectory()
    axes = tuple(InterpretationAxis(name, (name + "0", name + "1"), "fixture closed " + name, True)
                 for name in ("policy", "goal", "binding", "effect"))
    worlds = tuple(WorldPlan(f"w{i}", choice, (Obligation(f"o{i}", choice[0], "s0", atom(), True),))
                   for i, choice in enumerate(itertools.product(*(axis.choice_ids for axis in axes))))
    assert solve(ProofProblem(axes, worlds), ledger, REGISTRY).status is CoreStatus.PROVED_NO_ERROR
    assert solve(ProofProblem(axes, worlds[:-1]), ledger, REGISTRY).status is CoreStatus.UNRESOLVED


@pytest.mark.parametrize("must", [True, False])
def test_definitive_world_verdict_has_valid_independent_certificate(must):
    certificate, ctx, task, ledger = certified(must=must)
    assert certificate.status is (CoreStatus.PROVED_NO_ERROR if must else CoreStatus.PROVED_ERROR)
    assert check_certificate(certificate, ctx, task, ledger, REGISTRY).valid


def test_error_witness_does_not_require_complete_history_but_safety_does():
    certificate, ctx, task, ledger = certified(must=False, complete=False)
    assert check_certificate(certificate, ctx, task, ledger, REGISTRY).valid
    certificate, ctx, task, ledger = certified(must=True, complete=False)
    assert not check_certificate(certificate, ctx, task, ledger, REGISTRY).valid


@pytest.mark.parametrize("change", ["source", "witness", "status", "world", "assumptions", "authority"])
def test_certificate_tampering_is_rejected(change):
    certificate, ctx, task, ledger = certified()
    if change == "source":
        ctx = replace(ctx, prompt=ctx.prompt + " altered")
    elif change == "witness":
        primitive = replace(certificate.world_proofs[0].primitives[0], supports=("invented",))
        proof = replace(certificate.world_proofs[0], primitives=(primitive,))
        certificate = replace(certificate, world_proofs=(proof,))
    elif change == "status":
        certificate = replace(certificate, status=CoreStatus.PROVED_ERROR)
    elif change == "world":
        certificate = replace(certificate, world_proofs=())
    elif change == "assumptions":
        certificate = replace(certificate, completeness_assumptions=())
    else:
        ctx = replace(ctx, authoritative_axes=())
    assert not check_certificate(certificate, ctx, task, ledger, REGISTRY).valid


def test_schema_or_llm_confidence_cannot_authorize_semantic_closure():
    with pytest.raises(ValueError):
        AuthoritativeAxis("policy", ("h0",), "schema", "FINITE_TOOL_SCHEMA")


def test_empirical_candidate_consensus_error_does_not_claim_provable_closure_or_safety():
    certificate, ctx, task, ledger = certified(must=False)
    ctx = replace(ctx, authoritative_axes=(replace(ctx.authoritative_axes[0], authority_basis="EMPIRICAL_CANDIDATE_SET"),))
    certificate = replace(certificate, completeness_assumptions=completeness_assumptions(ctx, task, ledger))
    certificate = replace(certificate, source_sha256=digest(__import__('dataclasses').asdict(ctx)))
    assert check_certificate(certificate, ctx, task, ledger, REGISTRY).valid
    assert dict(certificate.completeness_assumptions)["SEMANTIC_SPACE_PROVABLY_CLOSED"] == "NOT_ESTABLISHED"
    certificate, ctx, task, ledger = certified(must=True)
    ctx = replace(ctx, authoritative_axes=(replace(ctx.authoritative_axes[0], authority_basis="EMPIRICAL_CANDIDATE_SET"),))
    certificate = replace(certificate, completeness_assumptions=completeness_assumptions(ctx, task, ledger))
    certificate = replace(certificate, source_sha256=digest(__import__('dataclasses').asdict(ctx)))
    assert not check_certificate(certificate, ctx, task, ledger, REGISTRY).valid


def test_noncanonical_expected_json_cannot_invert_truth_by_whitespace():
    with pytest.raises(ValueError):
        atom(expected_json=" true ")


def test_uncovered_material_semantics_is_unresolved_even_with_a_known_violation():
    _, _, ledger = trajectory()
    task = problem(must=False)
    task = replace(task, worlds=(replace(task.worlds[0], unresolved_reasons=(Reason.POLICY_OPEN_SEMANTICS,)),))
    assert solve(task, ledger, REGISTRY).status is CoreStatus.UNRESOLVED


def test_safety_certificate_cannot_silently_drop_factual_or_policy_obligations():
    certificate, ctx, task, ledger = certified()
    for dropped in range(2):
        modified = replace(task, worlds=(replace(task.worlds[0], obligations=task.worlds[0].obligations[dropped:dropped + 1]),))
        result = solve(modified, ledger, REGISTRY)
        cert = make_certificate(result, modified, ledger, REGISTRY, prompt=ctx.prompt, response=ctx.response,
            completeness_assumptions=completeness_assumptions(ctx, modified, ledger), validation_context=ctx)
        assert not check_certificate(cert, ctx, modified, ledger, REGISTRY).valid


def test_delete_restore_never_deleted_remains_false_while_current_entity_exists():
    from guardian_truth.vnext.normalize import tool_identity
    from guardian_truth.vnext.tools import ConditionalGuarantee, EffectSpec
    delete = replace(CONTRACT, identity=tool_identity("delete", {"record_id": "string"}, provider="fixture", version="v1"),
        guarantees=(ConditionalGuarantee(CONTRACT.guarantees[0].conditions, (EffectSpec("record_id", "exists", "false", True),)),))
    restore = replace(delete, identity=tool_identity("restore", {"record_id": "string"}, provider="fixture", version="v1"),
        guarantees=(ConditionalGuarantee(CONTRACT.guarantees[0].conditions, (EffectSpec("record_id", "exists", "true", True),)),))
    registry = ContractRegistry((delete, restore))
    prompt = ''
    for cid, name in [("d", "delete"), ("r", "restore")]:
        prompt += f'⟦ASSISTANT_TOOL_CALL name="{name}" call_id="{cid}"⟧\n{{"record_id":"Q-101"}}\n'
        prompt += f'⟦TOOL_RESULT name="{name}" requestor="assistant" call_id="{cid}"⟧\n{{"status":"completed"}}\n'
    events = normalize(prompt, "Q-101 was never deleted.", tool_identities=(delete.identity, restore.identity))
    effects = evaluate_t1(registry, events[0], events[1]).effects + evaluate_t1(registry, events[2], events[3]).effects
    ledger = replace(EvidenceLedger.from_events(events), effects=effects)
    never = atom(AtomKind.HISTORICAL_ACTION, predicate="delete", expected_json="false", time_index=4)
    assert prove_atom(never, ledger, LedgerIndex(ledger), registry).value is Truth.FALSE
    exists = atom(AtomKind.OBSERVED_STATE, predicate="exists", time_mode=TimeMode.AT, time_index=3, actor=None)
    assert prove_atom(exists, ledger, LedgerIndex(ledger), registry).value is Truth.TRUE
