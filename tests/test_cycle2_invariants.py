"""Promotion-blocking semantic invariants required by the Cycle 2 protocol."""

from guardian_truth.next.binder import bind_claim
from guardian_truth.next.claims import extract_claims_with_coverage
from guardian_truth.next.normalize import build_evidence, build_evidence_ledger, normalize_trace
from guardian_truth.next.records import (
    Claim, ClaimKind, EvidenceRecord, EvidenceStatus, FourValue, Span,
    ToolEffectContract,
)
from guardian_truth.next.trace_records import StateValidityStatus


OPEN, CLOSE = "\u27e6", "\u27e7"
SYSTEM = f"{OPEN}SYSTEM{CLOSE}\nMonitor the assistant."


def _claim(kind=ClaimKind.ACTION, predicate="cancelled", entities=()):
    return Claim("c", kind, "assistant", predicate, "completed", Span("response", 0, 1),
                 modality="completed", entities=entities)


def _failed_trace():
    return SYSTEM + (
        f'\n{OPEN}ASSISTANT_TOOL_CALL name="cancel" call_id="c1"{CLOSE}\n'
        '{"reservation_id":"R1"}'
        f'\n{OPEN}TOOL_RESULT name="cancel" requestor="assistant" call_id="c1"{CLOSE}\n'
        '{"success":false,"status":"failed"}'
    )


def test_user_action_is_not_assistant_action():
    extraction = extract_claims_with_coverage(
        f"{OPEN}USER{CLOSE}\nI cancelled reservation_id=R1."
    )
    assert extraction.claims == ()


def test_intent_is_not_completed():
    extraction = extract_claims_with_coverage(
        f"{OPEN}ASSISTANT{CLOSE}\nI will cancel reservation_id=R1."
    )
    assert [claim.kind for claim in extraction.claims] == [ClaimKind.INTENT]


def test_claim_is_not_observation():
    assert bind_claim(_claim(), []).status is FourValue.UNKNOWN


def test_failed_is_not_completed():
    evidence = build_evidence(normalize_trace(_failed_trace(), ""))
    assert any(item.status is EvidenceStatus.FAILED for item in evidence)
    assert not any(item.status is EvidenceStatus.CONFIRMED
                   and item.predicate == "effect_confirmed" for item in evidence)


def test_failed_is_not_no_effect_without_explicit_contract():
    contract = ToolEffectContract("cancel", guaranteed_effects=("cancelled",))
    evidence = build_evidence(normalize_trace(_failed_trace(), ""), {"cancel": contract})
    assert not any(item.predicate == "no_effect" for item in evidence)


def test_not_found_is_not_absence_without_completeness():
    evidence = [EvidenceRecord(
        "e", "event", "tool", "result", "not found", EvidenceStatus.OBSERVED,
        Span("prompt", 0, 1),
    )]
    assert bind_claim(_claim(ClaimKind.ABSENCE, "asserted_absence"), evidence).status is FourValue.UNKNOWN


def test_unknown_is_not_false():
    result = bind_claim(_claim(), [])
    assert result.status is FourValue.UNKNOWN
    assert result.status is not FourValue.FALSE


def test_proposal_is_not_execution():
    intent = _claim(ClaimKind.INTENT, "proposed_action")
    binding = bind_claim(intent, [])
    assert binding.status is FourValue.TRUE
    assert binding.reason == "intent_is_not_execution_claim"


def test_request_is_not_confirmation():
    extraction = extract_claims_with_coverage(
        f"{OPEN}ASSISTANT{CLOSE}\nPlease confirm reservation_id=R1?"
    )
    assert extraction.claims == ()
    assert extraction.coverage[0].status == "NON_VERIFIABLE"


def test_same_field_type_is_not_same_entity():
    claim = _claim(entities=(("reservation_id", "R1"),))
    evidence = [EvidenceRecord(
        "e", "event", "call", "effect_confirmed", "cancelled",
        EvidenceStatus.CONFIRMED, Span("prompt", 0, 1),
        entities=(("reservation_id", "R2"),),
    )]
    assert bind_claim(claim, evidence).status is FourValue.UNKNOWN


def test_stale_is_not_current():
    trace = SYSTEM + (
        f'\n{OPEN}ASSISTANT_TOOL_CALL name="read" call_id="c1"{CLOSE}\n'
        '{"line_id":"L1"}'
        f'\n{OPEN}TOOL_RESULT name="read" requestor="assistant" call_id="c1"{CLOSE}\n'
        '{"line_id":"L1","state":"old"}'
        f'\n{OPEN}ASSISTANT_TOOL_CALL name="read" call_id="c2"{CLOSE}\n'
        '{"line_id":"L1"}'
        f'\n{OPEN}TOOL_RESULT name="read" requestor="assistant" call_id="c2"{CLOSE}\n'
        '{"line_id":"L1","state":"new"}'
    )
    states = [item for item in build_evidence_ledger(normalize_trace(trace, "")).state_validity
              if item.predicate == "state"]
    assert [item.status for item in states] == [
        StateValidityStatus.SUPERSEDED_OBSERVATION,
        StateValidityStatus.ACTIVE_OBSERVATION,
    ]


def test_llm_interpretation_is_not_observed_fact():
    proposed_by_llm = _claim(predicate="cancelled", entities=(("reservation_id", "R1"),))
    attempted = [EvidenceRecord(
        "e", "event", "call", "call_attempted", "cancel",
        EvidenceStatus.ATTEMPTED, Span("prompt", 0, 1),
        entities=(("reservation_id", "R1"),), provenance="LLM_INTERPRETATION",
    )]
    assert bind_claim(proposed_by_llm, attempted).status is FourValue.UNKNOWN
