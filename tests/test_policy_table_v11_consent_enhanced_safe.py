import copy
import json

import pytest

from guardian_truth.policy_table_v11.consent_enhanced import explicit_confirmation_enhanced
from guardian_truth.policy_table_v11.witness import timeline
from test_policy_table_v11 import store, target


def check(text, reply='Yes', amount=2):
    extra = '⟦ASSISTANT⟧\n' + text + '\n' + (
        '⟦USER⟧\n' + reply + '\n' if reply is not None else '')
    s = store(extra, response='→ TOOL_CALL apply_a: ' + json.dumps({'record_id': 'X', 'amount': amount}))
    t = target(s)
    return explicit_confirmation_enhanced(s, t, timeline(s, t))


@pytest.mark.parametrize('text,amount', [
    ('Confirm applying to X?', 999),
    ('Confirm applying amount 2 to X-7?', 2),
    ('In your browser, apply amount 2 to X. Confirm?', 2),
    ('Do not apply amount 2 to X. Confirm?', 2),
    ('If external approval arrives, apply amount 2 to X. Confirm?', 2),
    ('Did you already apply amount 2 to X?', 2),
    ('Confirm executing inspect_b for record_id X and amount 2?', 2),
])
def test_unbound_prose_never_authorizes_native_operation(text, amount):
    assert check(text, amount=amount).status == 'UNRESOLVED'


@pytest.mark.parametrize('reply,want', [('Yes', True), ('No', False), ('Sure', True),
                                     ('No objections', True), ('Да', True), ('Нет', False)])
def test_complete_explicit_protocol_remains_usable(reply, want):
    got = check('Confirm apply_a: {"record_id":"X","amount":2}?', reply)
    assert (got.status, got.value) == ('RESOLVED', want)


@pytest.mark.parametrize('reply', ['Yes, but only after approval', 'No objections, change it to 999', '«Yes»'])
def test_complete_reply_must_be_inspected(reply):
    assert check('Confirm apply_a: {"record_id":"X","amount":2}?', reply).status == 'UNRESOLVED'


def test_identical_explicit_narration_preserves_prior_confirmation():
    s = store('⟦ASSISTANT⟧\nConfirm apply_a: {"record_id":"X","amount":2}?\n⟦USER⟧\nYes\n',
              response='⟦ASSISTANT⟧\nI will now call apply_a: {"record_id":"X","amount":2}\n'
                       '→ TOOL_CALL apply_a: {"record_id":"X","amount":2}')
    t = target(s)
    assert explicit_confirmation_enhanced(s, t, timeline(s, t)).value is True


def test_native_target_and_timeline_cannot_be_replaced():
    s = store('⟦ASSISTANT⟧\nConfirm apply_a: {"record_id":"X","amount":2}?\n⟦USER⟧\nYes\n')
    t = target(s)
    forged = copy.deepcopy(t)
    forged['arguments']['amount'] = 999
    assert explicit_confirmation_enhanced(s, forged, timeline(s, t)).status == 'UNRESOLVED'
    events = copy.deepcopy(timeline(s, t))
    events[-1][1].text = 'No'
    assert explicit_confirmation_enhanced(s, t, events).reason == 'timeline_not_native_source'
