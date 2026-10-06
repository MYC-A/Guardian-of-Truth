"""Contrast tests for the v6 audit: each pair = same mechanism, one admissible case and one violation.
Behavioural: they assert which findings DECIDE (MECHANICAL) or are reported, never module internals.
GUARDIAN_IMPL=v6 runs the same tests against the original v6 layers (expected to fail where the audit found defects)."""
import pytest

from v6fix_fixtures import IMPL, agent, call, f_findings, p_decisive, p_records, packet, res, rule, s_decisive, s_reported, user

NO_MAKE_UP = 'You should not make up any information or knowledge not provided by the user or the tools.'
new_only = pytest.mark.skipif(IMPL != 'v6fix', reason='provenance records exist only in v6fix')


# ============================================================== S: repeat / undeclared
def _repeat(result_payload, between=(), args=None, args_now=None):
    a = args or {'name': 'Ann Lee', 'zip': '12345'}
    h = [user('h0', 'Find me: Ann Lee, 12345'), call('h1', 'find_user', a), res('h2', 'find_user', result_payload), *between]
    return packet(h, [call('t0', 'find_user', args_now or a)])


def test_S_retry_after_transient_timeout_is_allowed_but_permanent_failure_is_reported():
    assert s_reported(_repeat('Error: request timed out, please try again later')) == []
    assert s_reported(_repeat('Error: user not found')) == ['REPEAT']


def test_S_user_asked_to_retry_is_allowed():
    assert s_reported(_repeat('Error: user not found', between=[user('h3', 'Please try that again.')])) == []
    assert s_reported(_repeat('Error: user not found')) == ['REPEAT']


def test_S_error_null_ok_true_is_not_a_failure():
    assert s_reported(_repeat({'error': None, 'ok': True, 'user_id': 'ann_1'})) == []
    assert s_reported(_repeat({'error': 'user not found', 'ok': False})) == ['REPEAT']


def test_S_out_of_order_results_are_not_paired_by_position():
    h = [user('h0', 'orders #1 and #2'), call('h1', 'get_order', {'order_id': '#1'}), call('h2', 'get_order', {'order_id': '#2'}),
         res('h3', 'get_order', 'Error: order #1 not found'), res('h4', 'get_order', {'order_id': '#2', 'status': 'pending'})]
    assert s_reported(packet(h, [call('t0', 'get_order', {'order_id': '#2'})])) == []        # which result is #2's is unknown
    h2 = [user('h0', 'order #2'), call('h1', 'get_order', {'order_id': '#2'}), res('h4', 'get_order', 'Error: order #2 not found')]
    assert s_reported(packet(h2, [call('t0', 'get_order', {'order_id': '#2'})])) == ['REPEAT']   # unambiguous pairing


def test_S_object_created_between_failed_lookup_and_repeat():
    h = [user('h0', 'ticket T1'), call('h1', 'lookup_ticket', {'ticket_id': 'T1'}), res('h2', 'lookup_ticket', 'Error: ticket not found'),
         call('h3', 'create_ticket', {'ticket_id': 'T1', 'subject': 'x'}), res('h4', 'create_ticket', {'ticket_id': 'T1'})]
    assert s_reported(packet(h, [call('t0', 'lookup_ticket', {'ticket_id': 'T1'})])) == []
    assert s_reported(packet(h[:3], [call('t0', 'lookup_ticket', {'ticket_id': 'T1'})])) == ['REPEAT']


def test_S_whitespace_is_part_of_the_argument_value():
    assert s_reported(_repeat('Error: user not found', args={'name': 'AnnLee', 'zip': '12345'}, args_now={'name': 'Ann Lee', 'zip': '12345'})) == []
    assert s_reported(_repeat('Error: user not found', args={'name': 'Ann Lee', 'zip': '12345'})) == ['REPEAT']


def test_S_permanent_vs_transient_structured_error():
    assert s_reported(_repeat({'error': 'Service temporarily unavailable (503)'})) == []
    assert s_reported(_repeat({'error': 'No user matches these details'})) == ['REPEAT']


def test_S_a_repeat_is_never_a_mechanical_error_without_a_norm():
    assert s_decisive(_repeat('Error: user not found')) == []


def test_S_undeclared_tool_only_in_complete_authoritative_catalog():
    t = [call('t0', 'device_reboot', {})]
    assert s_decisive(packet([user('h0', 'hi')], t, status={'device_reboot': 'UNDECLARED_IN_COMPLETE_PARSED_CATALOG'})) == ['UNDECLARED_TOOL']
    assert s_decisive(packet([user('h0', 'hi')], t, status={'device_reboot': 'NOT_FOUND_IN_UNVERIFIED_CATALOG'})) == []


# ============================================================== P: provenance
def _pay(args, history=None, policy=NO_MAKE_UP, complete=True, tool='pay'):
    h = history if history is not None else [user('h0', 'Pay my order #W1 please'),
                                             res('h1', 'get_order', {'order_id': '#W1', 'payment_methods': [{'id': 'credit_card_7'}]})]
    return packet(h, [call('t0', tool, args)], policy=policy, complete=complete)


def test_P_computed_amount_string_is_allowed_but_unseen_reference_is_not():
    assert p_decisive(_pay({'order_id': '#W1', 'payment_method_id': 'credit_card_7', 'amount': '1000'})) == []
    assert p_decisive(_pay({'order_id': '1000', 'payment_method_id': 'credit_card_7', 'amount': '10'})) == [('order_id', '1000')]


def test_P_new_id_allowed_by_contract_vs_unknown_existing_id():
    h = [user('h0', 'open a ticket about my delivery')]
    assert p_decisive(_pay({'ticket_id': 'T-777', 'subject': 'delivery'}, history=h, tool='create_ticket')) == []
    assert p_decisive(_pay({'ticket_id': 'T-777'}, history=h, tool='lookup_ticket')) == [('ticket_id', 'T-777')]


def test_P_unknown_opaque_id_needs_an_explicit_provenance_contract_to_decide():
    args = {'order_id': '#W9', 'payment_method_id': 'credit_card_7', 'amount': '5'}
    assert p_decisive(_pay(args)) == [('order_id', '#W9')]
    assert p_decisive(_pay(args, policy='Be helpful and concise.')) == []          # same fact, no contract -> hypothesis only


def test_P_identifiers_are_case_sensitive():
    h = [user('h0', 'pay'), res('h1', 'get_order', {'order_id': 'AB12cd', 'payment_methods': [{'id': 'credit_card_7'}]})]
    assert p_decisive(_pay({'order_id': 'AB12cd', 'payment_method_id': 'credit_card_7', 'amount': '1'}, history=h)) == []
    assert p_decisive(_pay({'order_id': 'ab12CD', 'payment_method_id': 'credit_card_7', 'amount': '1'}, history=h)) == [('order_id', 'ab12CD')]


def test_P_digits_inside_an_email_are_not_provenance():
    h_email = [user('h0', 'My email is ann.lee3019@x.com')]
    h_said = [user('h0', 'My order is 3019')]
    args = {'order_id': '3019', 'payment_method_id': 'x', 'amount': '1'}
    assert ('order_id', '3019') in p_decisive(_pay(args, history=h_email))
    assert ('order_id', '3019') not in p_decisive(_pay(args, history=h_said))


@new_only
def test_P_existing_id_of_another_entity_is_not_a_correct_binding():
    p = _pay({'order_id': '#W1', 'payment_method_id': '#W1', 'amount': '1'})
    r = p_records(p)[('payment_method_id', '#W1')]
    assert r['binding'] == 'UNVERIFIED' and r['status'] == 'FOUND_UNDER_OTHER_KEY'
    r_ok = p_records(_pay({'order_id': '#W1', 'payment_method_id': 'credit_card_7', 'amount': '1'}))[('order_id', '#W1')]
    assert r_ok['binding'] == 'UNVERIFIED'                     # provenance never certifies correctness


def test_P_incomplete_history_cannot_prove_absence():
    args = {'order_id': '#W9', 'payment_method_id': 'credit_card_7', 'amount': '5'}
    assert p_decisive(_pay(args, complete=False)) == []
    assert p_decisive(_pay(args, complete=True)) == [('order_id', '#W9')]


# ============================================================== F: turn-shape rules
ONE = 'You should only make one tool call at a time.'
TWO_CALLS = [call('t0', 'get_order', {'order_id': '#1'}), call('t1', 'get_order', {'order_id': '#2'})]


def _f(policy, runs, targets=TWO_CALLS, policy_id='q1', cache_from=None):
    return f_findings(packet([user('h0', 'hi')], targets, policy=policy, policy_id=policy_id), runs, cache_from=cache_from)


def test_F_same_policy_different_source_ids_is_rebound_per_input():
    r = [rule('MAX_TOOL_CALLS_PER_TURN', ONE, 1)] 
    a = packet([user('h0', 'hi')], TWO_CALLS, policy=ONE, policy_id='q1')
    b = packet([user('h0', 'hi')], TWO_CALLS, policy=ONE, policy_id='q7')
    assert [x[2] for x in f_findings(a, [r, r])] == ['q1']
    assert [x[2] for x in f_findings(b, [r, r], cache_from=a)] == ['q7']


def test_F_at_most_three_is_not_n1():
    pol = 'You may make at most three tool calls at a time.'
    assert [x for x in _f(pol, [[rule('MAX_TOOL_CALLS_PER_TURN', pol, 1)]] * 2) if x[1]] == []          # wrong n from the model
    assert [x for x in _f(pol, [[rule('MAX_TOOL_CALLS_PER_TURN', pol, 3)]] * 2) if x[1]] == []          # 2 calls <= 3
    four = [call(f't{i}', 'get_order', {'order_id': str(i)}) for i in range(4)]
    assert [x[0] for x in _f(pol, [[rule('MAX_TOOL_CALLS_PER_TURN', pol, 3)]] * 2, targets=four) if x[1]] == ['MAX_TOOL_CALLS_PER_TURN']


def test_F_permission_is_not_turned_into_a_prohibition():
    pol = 'You may make several tool calls at a time when that saves the user time.'
    assert [x for x in _f(pol, [[rule('MAX_TOOL_CALLS_PER_TURN', pol, 1)]] * 2) if x[1]] == []
    assert [x[0] for x in _f(ONE, [[rule('MAX_TOOL_CALLS_PER_TURN', ONE, 1)]] * 2) if x[1]] == ['MAX_TOOL_CALLS_PER_TURN']


def test_F_condition_from_the_previous_line_is_kept():
    pol = 'When the user is not yet authenticated:\n- You should only make one tool call at a time.'
    q = 'You should only make one tool call at a time.'
    assert [x for x in _f(pol, [[rule('MAX_TOOL_CALLS_PER_TURN', q, 1)]] * 2) if x[1]] == []
    assert [x[0] for x in _f('Rules:\n- ' + q, [[rule('MAX_TOOL_CALLS_PER_TURN', q, 1)]] * 2) if x[1]] == ['MAX_TOOL_CALLS_PER_TURN']


@pytest.mark.parametrize('pol,extra', [
    ('You should only make one tool call at a time, except for read-only lookups.', {}),
    ('For payment tools, you should only make one tool call at a time.', {'scope': 'payment tools'}),
    ('You should only make one tool call at a time.', {'subject': 'user'}),
])
def test_F_exception_scope_and_subject_are_kept(pol, extra):
    assert [x for x in _f(pol, [[rule('MAX_TOOL_CALLS_PER_TURN', pol, 1, **extra)]] * 2) if x[1]] == []
    assert [x[0] for x in _f(ONE, [[rule('MAX_TOOL_CALLS_PER_TURN', ONE, 1)]] * 2) if x[1]] == ['MAX_TOOL_CALLS_PER_TURN']


def test_F_no_rule_means_no_prohibition():
    assert _f('Be helpful.', [[], []]) == []
    assert [x[0] for x in _f(ONE, [[rule('MAX_TOOL_CALLS_PER_TURN', ONE, 1)]] * 2) if x[1]] == ['MAX_TOOL_CALLS_PER_TURN']


def test_F_partial_agreement_between_extractions_is_not_full_agreement():
    pol = 'You should only make one tool call at a time.\nMake one call per turn when the user is waiting.'
    a = [rule('MAX_TOOL_CALLS_PER_TURN', 'You should only make one tool call at a time.', 1)]
    b = [rule('MAX_TOOL_CALLS_PER_TURN', 'Make one call per turn when the user is waiting.', 1, condition='the user is waiting')]
    assert [x for x in _f(pol, [a, b]) if x[1]] == []
    assert [x[0] for x in _f(pol, [a, a]) if x[1]] == ['MAX_TOOL_CALLS_PER_TURN']


def test_F_message_with_tool_call_rule_and_its_own_trigger():
    pol = 'If you make a tool call, you should not respond to the user at the same time.'
    t = [agent('t0', 'Let me check.'), call('t1', 'get_order', {'order_id': '#1'})]
    r = [rule('NO_TEXT_WITH_TOOL_CALL', pol)]
    assert [x[0] for x in _f(pol, [r, r], targets=t) if x[1]] == ['NO_TEXT_WITH_TOOL_CALL']
    assert [x for x in _f(pol, [r, r], targets=t[1:]) if x[1]] == []


@new_only
def test_F_agreement_treats_agent_subject_spellings_as_one_but_not_other_subjects():
    # post-hoc (dev, before frozen120 evaluation): two runs differing only in subject 'agent' vs 'you' agree
    a, b = [rule('MAX_TOOL_CALLS_PER_TURN', ONE, 1, subject='agent')], [rule('MAX_TOOL_CALLS_PER_TURN', ONE, 1, subject='you')]
    assert [x[0] for x in _f(ONE, [a, b]) if x[1]] == ['MAX_TOOL_CALLS_PER_TURN']
    c = [rule('MAX_TOOL_CALLS_PER_TURN', ONE, 1, subject='user')]
    assert [x for x in _f(ONE, [a, c]) if x[1]] == []
