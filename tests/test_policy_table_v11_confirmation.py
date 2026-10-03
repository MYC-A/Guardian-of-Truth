import pytest
from test_policy_table_v11 import store, target
from guardian_truth.policy_table_v11.witness import explicit_confirmation

CONFIRMED = '⟦ASSISTANT⟧\nConfirm action on X?\n⟦USER⟧\nYes\n'
CALL = '→ TOOL_CALL apply_a: {"record_id":"X","amount":2}'


@pytest.mark.parametrize('extra,response,status,value', [
    # Restating the confirmed action in the target turn must not erase the earlier consent.
    (CONFIRMED, '⟦ASSISTANT⟧\nI will now apply the action to X.\n' + CALL, 'RESOLVED', True),
    (CONFIRMED, '⟦ASSISTANT⟧\nThank you, processing now.\n' + CALL, 'RESOLVED', True),
    # A new unanswered request for confirmation reopens the binding.
    (CONFIRMED, '⟦ASSISTANT⟧\nCan you confirm action on X once more?\n' + CALL, 'UNRESOLVED', None),
    # An identical retry keeps consent; a different native act consumes it.
    (CONFIRMED + '⟦ASSISTANT⟧\n' + CALL + '\n← TOOL_RESPONSE apply_a: {"error":"timeout"}\n', None, 'RESOLVED', True),
    (CONFIRMED + '⟦ASSISTANT⟧\n→ TOOL_CALL apply_a: {"record_id":"X","amount":5}\n← TOOL_RESPONSE apply_a: {"ok":true}\n', None, 'UNRESOLVED', None),
    # Conversation moving on after the reply is not silently carried forward.
    (CONFIRMED + '⟦ASSISTANT⟧\nAnything else?\n⟦USER⟧\nNo, stop, cancel it\n', None, 'UNRESOLVED', None),
])
def test_binding_survives_restatement_and_identical_retry_only(extra, response, status, value):
    s = store(extra, response=response); got = explicit_confirmation(s, target(s))
    assert (got.status, got.value) == (status, value)


@pytest.mark.parametrize('description,user,status,value', [
    ('Confirm action on X?', 'No problem, go ahead', 'RESOLVED', True),
    ('Подтвердите действие для X?', 'Нет возражений, подтверждаю', 'RESOLVED', True),
    ('Confirm action on X?', 'No problem', 'UNRESOLVED', None),
    ('Confirm action on X?', "Yes, don't touch the second record", 'UNRESOLVED', None),
    ('Confirm action on X-1?', 'Yes', 'UNRESOLVED', None),
    ('Confirm action on X.2?', 'Yes', 'UNRESOLVED', None),
    ('Confirm action on X.', 'Yes', 'RESOLVED', True),
])
def test_not_refusal_phrases_hedges_and_joined_ids(description, user, status, value):
    s = store('⟦ASSISTANT⟧\n' + description + '\n⟦USER⟧\n' + user + '\n'); got = explicit_confirmation(s, target(s))
    assert (got.status, got.value) == (status, value)
