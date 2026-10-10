from experiments.near_miss_20261010.detect import near_miss
from experiments.near_miss_20261010.policy import split, validate, vote
from experiments.contract_lint_20261010.lint import parse_catalog

PROMPT = """<policy>
Before cancelling, the agent must look up the order and check that its status is pending.
</policy>

[AVAILABLE TOOLS]
- get_order — Read an order.
    order_id: string! — The order id.
- cancel_order — Cancel an order.
    order_id: string! — The order id.
⟦USER⟧
cancel #W1 please
"""
QUOTE = 'the agent must look up the order and check that its status is pending'
SAMPLE = {'tools': {'get_order': {'mutating': False, 'requires': []},
                    'cancel_order': {'mutating': True, 'requires': [
                        {'need': 'status', 'satisfied_by': ['get_order'], 'entity_arg': 'order_id', 'policy_quote': QUOTE}]}}}


def cat():
    return parse_catalog(PROMPT)


def test_validate_keeps_verbatim_and_drops_bad():
    pol = split(PROMPT)[0]
    assert len(validate(SAMPLE, pol, cat())['requires']) == 1
    bad = {'tools': {'get_order': {'mutating': False}, 'cancel_order': {'mutating': True, 'requires': [
        {'satisfied_by': ['get_order'], 'entity_arg': 'order_id', 'policy_quote': 'invented requirement text here'},
        {'satisfied_by': ['nope'], 'entity_arg': 'order_id', 'policy_quote': QUOTE},
        {'satisfied_by': ['get_order'], 'entity_arg': 'oid', 'policy_quote': QUOTE},
        {'satisfied_by': ['cancel_order'], 'entity_arg': 'order_id', 'policy_quote': QUOTE}]}}}
    v = validate(bad, pol, cat())
    assert v['requires'] == [] and v['dropped'] == {'quote': 1, 'satisfied_by': 2, 'entity_arg': 1}
    assert validate('not json', pol, cat()) is None


def test_vote_quorum():
    pol = split(PROMPT)[0]
    one = validate(SAMPLE, pol, cat())
    empty = validate({'tools': {'get_order': {'mutating': False}, 'cancel_order': {'mutating': True}}}, pol, cat())
    assert len(vote([one, one, empty])['requires']) == 1
    assert vote([one, empty, None])['requires'] == []


def m():
    return vote([validate(SAMPLE, split(PROMPT)[0], cat())] * 3)


def turn(call):
    return '⟦ASSISTANT · ход 2⟧\n\t→ TOOL_CALL ' + call


def test_fires_without_read_of_same_entity():
    assert [f['check'] for f in near_miss(PROMPT, turn('cancel_order: {"order_id": "#W1"}'), m())] == ['NEAR_MISS']
    other = PROMPT + '⟦ASSISTANT · ход 1⟧\n\t→ TOOL_CALL get_order: {"order_id": "#W9"}\n\t← TOOL_RESPONSE get_order: {"status": "pending"}\n'
    assert len(near_miss(other, turn('cancel_order: {"order_id": "#W1"}'), m())) == 1


def test_satisfied_by_successful_read_or_entity_in_body():
    ok = PROMPT + '⟦ASSISTANT · ход 1⟧\n\t→ TOOL_CALL get_order: {"order_id": "#W1"}\n\t← TOOL_RESPONSE get_order: {"status": "pending"}\n'
    assert near_miss(ok, turn('cancel_order: {"order_id": "#W1"}'), m()) == []
    body = PROMPT + '⟦ASSISTANT · ход 1⟧\n\t→ TOOL_CALL get_order: {"order_id": "x"}\n\t← TOOL_RESPONSE get_order: {"orders": ["#W1"]}\n'
    assert near_miss(body, turn('cancel_order: {"order_id": "#W1"}'), m()) == []


def test_failed_read_does_not_count_and_unknown_pairing_is_lenient():
    err = PROMPT + '⟦ASSISTANT · ход 1⟧\n\t→ TOOL_CALL get_order: {"order_id": "#W1"}\n\t← TOOL_RESPONSE get_order [ERROR]: down\n'
    assert len(near_miss(err, turn('cancel_order: {"order_id": "#W1"}'), m())) == 1
    unk = PROMPT + '⟦ASSISTANT · ход 1⟧\n\t→ TOOL_CALL get_order: {"order_id": "#W1"}\n'
    assert near_miss(unk, turn('cancel_order: {"order_id": "#W1"}'), m()) == []


def test_read_turn_and_no_map_never_fire():
    assert near_miss(PROMPT, turn('get_order: {"order_id": "#W1"}'), m()) == []
    assert near_miss(PROMPT, turn('cancel_order: {"order_id": "#W1"}'), None) == []
