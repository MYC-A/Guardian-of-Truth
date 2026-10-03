from types import SimpleNamespace as E
from guardian_truth.policy_table_v11.policy_clauses import turn_shape_violations
from guardian_truth.policy_table_v11.admissibility import _contact_grounded, _contact
from guardian_truth.policy_table_v11.router import Route


def _store(policy):
    return E(history_events=[E(role='system', text=policy, kind='text')])


ONE = 'You should only make one tool call at a time, and if you make a tool call, you should not respond to the user simultaneously.'


def test_multiple_calls_need_explicit_clause():
    two = Route('TOOL_CALL', ('t0', 't1'))
    assert turn_shape_violations(_store(ONE), two)[0]['code'] == 'MULTIPLE_TOOL_CALLS_IN_STEP'
    assert not turn_shape_violations(_store('Be helpful.'), two)
    assert not turn_shape_violations(_store(ONE), Route('TOOL_CALL', ('t0',)))


def test_call_with_message_needs_explicit_clause():
    mixed = Route('MIXED', ('t0',), ('t1',))
    assert [v['code'] for v in turn_shape_violations(_store(ONE), mixed)] == ['CALL_WITH_USER_MESSAGE']
    assert not turn_shape_violations(_store('Be helpful.'), mixed)


def test_contact_value_must_be_standalone_token():
    corpus = 'user: my email is sofia.thomas3019@example.com, zip 80273'
    assert _contact('zip', '3019') and not _contact_grounded(corpus, '3019')
    assert _contact_grounded(corpus, '80273')
    assert _contact_grounded(corpus, 'Sofia.Thomas3019@example.com')
    assert _contact_grounded('phone: +1 (555) 123-4567', '5551234567')
    assert not _contact('first_name', 'Sofia')
