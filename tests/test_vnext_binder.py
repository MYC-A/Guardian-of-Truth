from dataclasses import replace

import pytest

from guardian_truth.vnext.binder import bind_claim
from guardian_truth.vnext.ledger import EvidenceLedger, LedgerIndex
from guardian_truth.vnext.normalize import normalize
from guardian_truth.vnext.types import ClaimKind, Disposition, Reason, Span, TypedClaim


def claim(ref="Q-101", **changes):
    value = TypedClaim("s0", Span("response", 0, 5), Disposition.VERIFIABLE_TYPED,
                      ClaimKind.ACTION_COMPLETED, "assistant", "archive", ref, (ref,),
                      "POSITIVE", "ASSERTED", "PAST", ("ASSISTANT",))
    return replace(value, **changes)


def ledger(payload='{"record_id":"Q-101"}'):
    text = '⟦ASSISTANT_TOOL_CALL name="archive" call_id="a"⟧\n' + payload
    text += '\n⟦TOOL_RESULT name="archive" requestor="assistant" call_id="a"⟧\n{"status":"completed"}'
    return EvidenceLedger.from_events(normalize(text, ""), history_complete=True, completeness_basis="controlled full trace")


def test_indexed_binding_expands_exact_call_to_result_without_inherited_entity_guess():
    value = ledger()
    bound = bind_claim(claim(), value, LedgerIndex(value))
    assert len(bound.alternatives) == 1
    assert bound.alternatives[0].event_ids == ("e0", "e1")
    assert len(bound.alternatives[0].evidence_ids) == 1
    assert bound.candidate_search.candidate_set_complete


def test_retrieval_miss_is_unknown_not_absence():
    value = ledger()
    bound = bind_claim(claim("missing"), value, LedgerIndex(value))
    assert bound.alternatives == ()
    assert Reason.ENTITY_UNBOUND in bound.reasons
    assert not bound.candidate_search.candidate_set_complete


def test_duplicate_names_are_distinct_explicit_identity_candidates():
    text = '⟦TOOL_RESULT name="list" requestor="assistant"⟧\n'
    text += '{"records":[{"id":"Q-101","name":"Alex"},{"id":"Q-102","name":"Alex"}]}'
    value = EvidenceLedger.from_events(normalize(text, ""), history_complete=True, completeness_basis="controlled full trace")
    bound = bind_claim(claim("Alex"), value, LedgerIndex(value))
    assert len(bound.alternatives) == 2
    assert Reason.ENTITY_AMBIGUOUS in bound.reasons
    assert not bound.candidate_search.candidate_set_complete


def test_unresolved_time_and_source_are_explicit():
    value = ledger()
    bound = bind_claim(claim(time_anchor="YESTERDAY", source_refs=("UNKNOWN",)), value, LedgerIndex(value))
    assert Reason.TIME_UNBOUND in bound.reasons
    assert Reason.SOURCE_UNBOUND in bound.reasons


def test_index_snapshot_cannot_silently_go_stale():
    value = ledger()
    with pytest.raises(ValueError, match="stale"):
        bind_claim(claim(), replace(value, history_complete=False), LedgerIndex(value))
