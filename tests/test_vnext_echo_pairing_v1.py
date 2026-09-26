"""Adversarial pairing controls for result-echo repair."""

from guardian_truth.vnext.echo_pairing_v1 import ReadEchoContract, pair_read_echoes
from guardian_truth.vnext.normalize import normalize, tool_identity


IDENTITY = tool_identity("read_order", {"order_id": "string"},
                         provider="fixture", version="1")
OTHER = tool_identity("read_order", {"order_id": "string"},
                      provider="fixture", version="2")
CONTRACT = ReadEchoContract(IDENTITY, ("order_id",), (("order_id",),),
                            "reviewed fixture: result.order_id echoes request.order_id")


def trace(*, ids=("A", "B"), results=("B", "A"), result_header="", second_identity=False):
    calls = [f'⟦ASSISTANT_TOOL_CALL name="read_order"⟧\n{{"order_id":"{entity}"}}\n'
             for entity in ids]
    outputs = [f'⟦TOOL_RESULT name="read_order" requestor="assistant" {result_header}⟧\n'
               f'{{"order_id":"{entity}"}}\n' for entity in results]
    text = "".join(calls + outputs)
    identities = (IDENTITY, OTHER) if second_identity else (IDENTITY,)
    return normalize(text, "", tool_identities=identities)


def test_distinct_pending_calls_pair_by_exact_result_echo_even_out_of_order():
    original = trace()
    assert all(event.call_id is None for event in original[2:])
    repaired = pair_read_echoes(original, (CONTRACT,))
    assert repaired.rebound_result_ids == ("e2", "e3")
    assert [event.call_id for event in repaired.events[2:]] == ["call:e1", "call:e0"]


def test_duplicate_requested_entity_keeps_ambiguity():
    original = trace(ids=("A", "A"), results=("A",))
    repaired = pair_read_echoes(original, (CONTRACT,))
    assert not repaired.rebound_result_ids
    assert repaired.events[-1].call_id is None


def test_unmatched_entity_or_explicit_transport_id_is_never_guessed():
    wrong_entity = pair_read_echoes(trace(results=("C",)), (CONTRACT,))
    assert wrong_entity.events[-1].call_id is None
    explicit = pair_read_echoes(trace(results=("B",), result_header='call_id="bad"'), (CONTRACT,))
    assert explicit.events[-1].call_id is None


def test_no_contract_or_ambiguous_tool_version_cannot_rebind():
    assert not pair_read_echoes(trace(), ()).rebound_result_ids
    # Two supplied identities with the same name leave the parser's identity
    # unversioned, so the reviewed v1 contract cannot attach to it.
    assert not pair_read_echoes(trace(second_identity=True), (CONTRACT,)).rebound_result_ids


def test_conflicting_result_id_fields_do_not_pick_one():
    contract = ReadEchoContract(IDENTITY, ("order_id",), (("order_id",), ("other_order_id",)),
                                "reviewed fixture")
    original = trace(results=("B",))
    result = original[-1]
    from dataclasses import replace
    from guardian_truth.vnext.integrity import canonical
    altered = (*original[:-1], replace(result, payload_json=canonical(
        {"order_id": "B", "other_order_id": "A"}).decode()))
    assert not pair_read_echoes(altered, (contract,)).rebound_result_ids


def test_missing_required_echo_field_does_not_pick_one():
    contract = ReadEchoContract(IDENTITY, ("order_id",), (("order_id",), ("other_order_id",)),
                                "reviewed fixture")
    assert not pair_read_echoes(trace(results=("B",)), (contract,)).rebound_result_ids


def test_one_pending_call_cannot_support_two_unidentified_results():
    repaired = pair_read_echoes(trace(ids=("A", "B"), results=("B", "B")), (CONTRACT,))
    assert repaired.rebound_result_ids == ("e2",)
    assert repaired.events[-1].pairing_issue == "AMBIGUOUS_CALL_IDENTITY"
