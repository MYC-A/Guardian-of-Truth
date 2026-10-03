from types import SimpleNamespace as E
from guardian_truth.policy_table_v11.invariants import (placeholder_violations, noop_replacement_violations,
                                                        repeated_failed_call_violations)


def test_placeholder_including_wrapped_json_arguments():
    assert placeholder_violations({'arguments': '{"account_id": "blue_account_id_placeholder"}'})
    assert placeholder_violations({'id': '<ORDER_ID>'})
    assert not placeholder_violations({'id': 'acc_93812', 'note': 'Placed order yesterday'})


def test_noop_replacement_same_position_only():
    assert noop_replacement_violations({'item_ids': ['1', '2'], 'new_item_ids': ['3', '2']})[0]['positions'] == [1]
    assert not noop_replacement_violations({'item_ids': ['1', '2'], 'new_item_ids': ['2', '1']})
    assert noop_replacement_violations({'flight': 'A', 'new_flight': 'A'})


def test_repeated_failed_call_needs_identical_args_and_error():
    failed = E(kind='call', name='find', value=None, text='{"zip": "1"}\n\t← TOOL_RESPONSE find [ERROR]: not found')
    ok = E(kind='call', name='find', value=None, text='{"zip": "1"}\n\t← TOOL_RESPONSE find: {"id": 7}')
    assert repeated_failed_call_violations([failed], 'find', {'zip': '1'})
    assert not repeated_failed_call_violations([failed], 'find', {'zip': '2'})
    assert not repeated_failed_call_violations([failed, ok], 'find', {'zip': '1'})
