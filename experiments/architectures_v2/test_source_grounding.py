from __future__ import annotations

from experiments.architectures_v2.source_grounding import (
    AtomicSuspicion,
    SpanClaim,
    validate_suspicion,
)


SOURCES = {
    "prompt": "Policy: verify identity before transfer. verify identity.",
    "response": "I attempted the transfer, but the call failed.",
}


def suspicion(source: SpanClaim, **changes) -> AtomicSuspicion:
    values = {
        "reason_type": "policy_order",
        "source_kind": "SYSTEM_POLICY",
        "source": source,
        "target": SpanClaim("response", "attempted", 2, 11),
        "proposed_violation": "transfer preceded verification",
        "score": 0.9,
        "reason_attributes": {"knowledge": "unknown", "execution": "attempted"},
    }
    values.update(changes)
    return AtomicSuspicion(**values)


def test_exact_offsets_anchor_and_keep_formal_status_separate():
    record = validate_suspicion(
        suspicion(SpanClaim("prompt", "verify identity", 8, 23)), SOURCES
    )
    assert record.grounding_status == "ANCHORED"
    assert record.probabilistic_label == 1
    assert record.formal_status == "UNRESOLVED"


def test_wrong_offsets_are_unanchored_and_cannot_be_positive():
    record = validate_suspicion(
        suspicion(SpanClaim("prompt", "verify identity", 9, 24)), SOURCES
    )
    assert record.grounding_status == "UNANCHORED"
    assert record.probabilistic_label == 0
    assert "source_quote_offset_mismatch" in record.issues


def test_unique_quote_can_recover_offsets():
    record = validate_suspicion(
        suspicion(SpanClaim("prompt", "before transfer")), SOURCES
    )
    assert (record.source_start, record.source_end) == (24, 39)
    assert record.grounding_status == "ANCHORED"


def test_repeated_quote_without_offsets_is_ambiguous():
    record = validate_suspicion(
        suspicion(SpanClaim("prompt", "verify identity")), SOURCES
    )
    assert "source_quote_ambiguous" in record.issues
    assert record.probabilistic_label == 0


def test_unknown_document_is_unanchored():
    record = validate_suspicion(
        suspicion(SpanClaim("tool_result", "verify identity")), SOURCES
    )
    assert record.issues == ("source_unknown_document",)


def test_unknown_and_attempted_attributes_are_preserved_without_inference():
    record = validate_suspicion(
        suspicion(SpanClaim("prompt", "before transfer")), SOURCES
    )
    assert record.suspicion.reason_attributes == {
        "knowledge": "unknown",
        "execution": "attempted",
    }
    assert "false" not in record.to_dict()["suspicion"]["reason_attributes"].values()
    assert "completed" not in record.to_dict()["suspicion"]["reason_attributes"].values()


def test_invalid_score_is_rejected():
    try:
        validate_suspicion(
            suspicion(SpanClaim("prompt", "before transfer"), score=1.1), SOURCES
        )
    except ValueError as error:
        assert "score" in str(error)
    else:
        raise AssertionError("invalid score was accepted")
