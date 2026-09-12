from dataclasses import FrozenInstanceError, replace

import pytest

from guardian_truth.vnext.ledger import EvidenceLedger, LedgerIndex
from guardian_truth.vnext.normalize import normalize, tool_identity
from guardian_truth.vnext.types import EntityRef


def call(cid="a", actor="ASSISTANT", name="archive", payload='{"record_id":"Q-1"}'):
    return f'⟦{actor}_TOOL_CALL name="{name}" call_id="{cid}"⟧\n{payload}\n'


def result(cid="a", requestor="assistant", name="archive", payload='{"record_id":"Q-1","archived":true}'):
    return f'⟦TOOL_RESULT name="{name}" requestor="{requestor}" call_id="{cid}"⟧\n{payload}\n'


def test_roles_order_offsets_and_explicit_pairing_are_lossless():
    prompt = '⟦SYSTEM⟧\nNever guess.\n⟦USER⟧\nPlease archive.\n' + call() + result()
    response = '⟦ASSISTANT⟧\nI archived it.'
    events = normalize(prompt, response)
    assert [event.index for event in events] == list(range(len(events)))
    for event in events:
        doc = prompt if event.source.document == "prompt" else response
        assert doc[event.source.start:event.source.end] == event.raw_text
    calls = [event for event in events if event.kind == "call"]
    results = [event for event in events if event.kind == "result"]
    assert calls[0].actor == "assistant"
    assert results[0].actor == "tool"
    assert results[0].requestor == "assistant"
    assert results[0].call_id == calls[0].call_id


@pytest.mark.parametrize("prefix,suffix", [
    (call("a"), result("wrong")),
    (call("a", "USER"), result("a")),
    (call("a", name="archive"), result("a", name="delete")),
])
def test_explicit_mismatch_is_not_repaired_by_fifo(prefix, suffix):
    events = normalize(prefix + suffix, "")
    assert events[-1].call_id is None
    assert events[-1].pairing_issue == "UNMATCHED_CALL_IDENTITY"


def test_duplicate_call_ids_preserve_all_plausible_candidates():
    events = normalize(call("a") + call("a") + result("a"), "")
    assert events[-1].call_id is None
    assert len(events[-1].call_candidates) == 2
    assert events[-1].pairing_issue == "AMBIGUOUS_CALL_IDENTITY"


def test_missing_id_with_multiple_calls_is_not_fifo_guess():
    no_id = result().replace(' call_id="a"', "")
    events = normalize(call("a") + call("b") + no_id, "")
    assert events[-1].call_id is None
    assert len(events[-1].call_candidates) == 2


def test_unique_missing_id_can_pair_but_unknown_actor_cannot():
    no_id = result().replace(' call_id="a"', "")
    events = normalize(call("a") + no_id, "")
    assert events[-1].call_id == events[0].call_id
    unknown = result(requestor="unknown")
    assert normalize(call("a") + unknown, "")[-1].call_id is None


def test_payload_views_cannot_mutate_immutable_events():
    event = normalize(call(payload='{"record_id":"Q-1","nested":{"v":1}}'), "")[0]
    view = event.payload
    view["nested"]["v"] = 99
    assert event.payload["nested"]["v"] == 1
    with pytest.raises(FrozenInstanceError):
        event.actor = "user"


def test_tool_metadata_is_exact_versioned_schema_hash():
    identity = tool_identity("archive", {"v": 1}, provider="fixture", version="v1")
    changed = tool_identity("archive", {"v": 2}, provider="fixture", version="v1")
    assert changed.schema_sha256 != identity.schema_sha256
    event = normalize(call(), "", tool_identities=(identity,))[0]
    assert event.tool == identity
    conflict = normalize(call(), "", tool_identities=(identity, changed))[0]
    assert conflict.tool.schema_sha256 is None


def test_timestamp_and_nested_entity_ids_are_preserved_not_interpreted():
    text = call(payload='{"nested":{"entity_id":7},"name":"Alex"}').replace('call_id="a"', 'call_id="a" timestamp="2026-01-01"')
    event = normalize(text, "")[0]
    assert event.timestamp == "2026-01-01"
    assert EntityRef("nested.entity_id", "7") in event.entity_refs
    assert any(entity.key == "name" and entity.value == "Alex" for entity in event.entity_refs)


def test_claim_intent_and_attempt_do_not_become_observed_business_effects():
    ledger = EvidenceLedger.from_events(normalize(call(), "I archived Q-1. I will archive Q-2."))
    assert ledger.observations == ()
    assert ledger.effects_of("e0") == ()


def test_failure_and_not_found_are_observed_fields_not_no_effect_or_absence():
    ledger = EvidenceLedger.from_events(normalize(call() + result(payload='{"status":"failed","error":"not found"}'), ""))
    assert {item.predicate for item in ledger.observations} == {"status", "error"}
    assert ledger.effects_of("e1") == ()


def test_forged_observation_cannot_enter_ledger():
    ledger = EvidenceLedger.from_events(normalize(call() + result(), ""))
    forged = replace(ledger.observations[0], value_json='"invented"')
    with pytest.raises(ValueError, match="reconstructed"):
        replace(ledger, observations=(forged,) + ledger.observations[1:])


def test_append_preserves_old_snapshot_and_invalidates_completeness():
    initial = normalize(call() + result(), "")
    ledger = EvidenceLedger.from_events(initial, history_complete=True, completeness_basis="explicit complete supplied prefix")
    following = normalize(call("b") + result("b", payload='{"record_id":"Q-1","archived":false}'), "")
    # Normalizer handles whole documents; append caller assigns stable global IDs.
    added = tuple(replace(event, index=event.index + len(initial), event_id=f"e{event.index + len(initial)}",
                          call_id="call:e2") for event in following)
    updated = ledger.append(added)
    assert ledger.events == initial and len(updated.events) == 4
    assert updated.observations[:len(ledger.observations)] == ledger.observations
    assert not updated.history_complete
    assert [item.value for item in updated.observations if item.predicate == "archived"] == [True, False]


def test_history_and_state_time_queries_do_not_erase_or_assume_persistence():
    text = call() + result() + call("b") + result("b", payload='{"record_id":"Q-1","archived":false}')
    ledger = EvidenceLedger.from_events(normalize(text, ""))
    entity = EntityRef("record_id", "Q-1")
    assert len(ledger.history(entity)) == 4
    assert [item.value for item in ledger.state_at(entity, 1, predicate="archived")] == [True]
    assert [item.value for item in ledger.state_at(entity, 3, predicate="archived")] == [False]
    assert ledger.state_at(entity, 4, predicate="archived") == ()
    old = ledger.state_at(entity, 1, predicate="archived")[0]
    assert ledger.known_at(old, 3)  # historical observation is still known
    assert not ledger.known_at(old, 0)
    assert [item.value for item in ledger.latest_confirmed_state(entity, 3, predicate="archived")] == [False]
    assert len(ledger.events_between(1, 2)) == 2
    assert len(ledger.calls_of(tool="archive", entity=entity)) == 2
    assert len(ledger.results_of(ledger.events[0].call_id)) == 1


def test_empty_retrieval_is_not_complete_without_scope_certificate():
    ledger = EvidenceLedger.from_events(normalize(call(), ""))
    found = LedgerIndex(ledger).search(entity=EntityRef("record_id", "missing"))
    assert found.event_ids == ()
    assert not found.candidate_set_complete
    with pytest.raises(ValueError):
        EvidenceLedger.from_events(ledger.events, history_complete=True)


def test_all_indexes_and_time_range_are_exact_and_semantic_selector_is_open():
    events = normalize(call() + result(), "I archived it.")
    ledger = EvidenceLedger.from_events(events, history_complete=True, completeness_basis="source supplied trace slice")
    index = LedgerIndex(ledger)
    found = index.search(entity=EntityRef("record_id", "Q-1"), actor="assistant", tool="archive",
                         call=events[0].call_id, source="prompt", event_type="call", time_range=(0, 1))
    assert found.event_ids == (events[0].event_id,)
    assert set(found.searched_indexes) == {"entity", "actor", "tool", "call", "source", "type", "time"}
    assert found.candidate_set_complete
    assert not index.search(unresolved_selectors=("old records",)).candidate_set_complete


@pytest.mark.parametrize("count", [100, 1000, 10000])
def test_long_trace_retrieval_has_no_top_k_truth_cap(count):
    base = normalize(call(), "")[0]
    events = tuple(replace(base, event_id=f"e{i}", index=i, call_id=f"call:e{i}") for i in range(count))
    ledger = EvidenceLedger.from_events(events, history_complete=True, completeness_basis="controlled full trace")
    found = LedgerIndex(ledger).search(entity=EntityRef("record_id", "Q-1"))
    assert len(found.event_ids) == count
    assert found.event_ids[-1] == f"e{count-1}"
    assert found.candidate_set_complete
