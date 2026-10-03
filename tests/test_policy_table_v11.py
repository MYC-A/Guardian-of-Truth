import json
from pathlib import Path
import pytest
from guardian_truth.source_search.store import SourceStore
from guardian_truth.source_search.id_contract import native_target_inventory
from guardian_truth.policy_table.segment import policy_hash, clauses
from guardian_truth.policy_table_v11.catalog import normalize_catalog
from guardian_truth.policy_table_v11.schema import Atom, Expression
from guardian_truth.policy_table_v11.compile import (admit, assemble, canonical, request, verify_table)
from guardian_truth.policy_table_v11.evaluate import evaluate_atom, evaluate_table
from guardian_truth.policy_table_v11.witness import explicit_confirmation, current_datetime


def store(extra='', response=None, policy='Before apply_a obtain explicit confirmation. Never proceed with blocked state.'):
    return SourceStore({'prompt': '⟦SYSTEM⟧\n' + policy + '\n[AVAILABLE TOOLS]\n- apply_a — modify a record\n    record_id: string!\n    amount: number!\n- inspect_b — inspect a record\n    record_id: string!\n- get_current_time — get current time\n⟦USER⟧\nPlease inspect X.\n' + extra,
        'response': response or '→ TOOL_CALL apply_a: {"record_id":"X","amount":2}'})


def policy(s): return {'policy_sha256': policy_hash(s), 'clauses': clauses(s), 'catalog': normalize_catalog([s])}
def target(s): return native_target_inventory(s)[0]
def atomic(**changes):
    return Atom.model_validate({'modality': 'REQUIRES_USER_CONFIRMATION', 'confirmation': True,
        'clause_ids': ['clause_0'], 'exceptions': [], **changes})
def comparison(path='args.amount', op='==', value=2, **kw):
    return {'kind': 'COMPARE', 'lhs': path, 'op': op, 'rhs': {'kind': 'LITERAL', 'value': value}, **kw}


@pytest.mark.parametrize('description,user,status,value', [
    ('Confirm apply_a: {"record_id":"X","amount":2}?', 'Yes', 'RESOLVED', True),
    ('Подтвердите apply_a: {"record_id":"X","amount":2}?', 'Да', 'RESOLVED', True),
    ('Подтвердите apply_a: {"record_id":"X","amount":2}?', 'Подтверждаю.', 'RESOLVED', True),
    ('Confirm apply_a: {"record_id":"X","amount":2}?', 'Go ahead', 'RESOLVED', True),
    ('Подтвердите apply_a: {"record_id":"X","amount":2}?', 'Согласна', 'RESOLVED', True),
    ('Confirm apply_a: {"record_id":"X","amount":2}?', 'Yes please', 'RESOLVED', True),
    ('Подтвердите apply_a: {"record_id":"X","amount":2}?', 'Нет', 'RESOLVED', False),
    ('Confirm apply_a: {"record_id":"X","amount":2}?', 'Do not proceed', 'RESOLVED', False),
    ('Confirm apply_a: {"record_id":"X","amount":2}?', None, 'RESOLVED', False),
    ('Подтвердите apply_a: {"record_id":"X","amount":2}?', None, 'RESOLVED', False),
    ('Confirm apply_a: {"record_id":"Y","amount":2}?', 'Yes', 'UNRESOLVED', None),
    ('Confirm apply_a: {"record_id":"X","amount":2}?', 'Yes, but only if allowed', 'UNRESOLVED', None),
    ('Подтвердите действие для X?', 'Какова стоимость?', 'UNRESOLVED', None),
    ('The record X exists.', 'Yes', 'UNRESOLVED', None),
])
def test_confirmation_ru_en(description, user, status, value):
    extra = '⟦ASSISTANT⟧\n' + description + ('\n⟦USER⟧\n' + user if user is not None else '') + '\n'
    s = store(extra); got = explicit_confirmation(s, target(s))
    assert (got.status, got.value) == (status, value)


def test_confirmation_does_not_cross_native_act_or_accept_stale_yes():
    s = store('⟦ASSISTANT⟧\nConfirm apply_a: {"record_id":"X","amount":2}?\n⟦USER⟧\nYes\n⟦ASSISTANT⟧\n→ TOOL_CALL inspect_b: {"record_id":"X"}\n')
    assert explicit_confirmation(s, target(s)).status == 'UNRESOLVED'
    s = store('⟦USER⟧\nYes\n⟦ASSISTANT⟧\nConfirm apply_a: {"record_id":"X","amount":2}?\n')
    assert explicit_confirmation(s, target(s)).value is False


@pytest.mark.parametrize('user', ['Cancel it', 'Отмените', 'Отмените его, пожалуйста', 'No problem, go ahead',
    'Нет, всё верно', 'Нет возражений', 'Stop asking, just do it', "Don't worry, proceed", 'Не против'])
def test_action_verbs_and_negated_courtesy_are_not_refusals(user):
    # FALSE is positive evidence of a violation; these replies must never produce it.
    s = store('⟦ASSISTANT⟧\nShall I cancel X?\n⟦USER⟧\n' + user + '\n')
    assert explicit_confirmation(s, target(s)).value is not False


@pytest.mark.parametrize('user', ['No', 'Нет', 'Нет, спасибо', 'No, thanks.', 'Не надо', 'Do not proceed', "Please don't",
    'Не подтверждаю', 'Нет, не надо', 'No. I changed my mind'])
def test_narrow_explicit_refusals(user):
    s = store('⟦ASSISTANT⟧\nConfirm apply_a: {"record_id":"X","amount":2}?\n⟦USER⟧\n' + user + '\n')
    got = explicit_confirmation(s, target(s))
    assert (got.status, got.value, got.reason) == ('RESOLVED', False, 'EXPLICIT_REFUSAL_AFTER_BOUND_DESCRIPTION')


@pytest.mark.parametrize('narration', ['I will call apply_a: {"record_id":"X","amount":2}', 'Вызову apply_a: {"record_id":"X","amount":2}',
    'I will call apply_a: {"record_id":"X","amount":2}'])
def test_bound_narration_after_confirmation_is_not_an_unanswered_request(narration):
    s = store('⟦ASSISTANT⟧\nConfirm apply_a: {"record_id":"X","amount":2}?\n⟦USER⟧\nYes\n⟦ASSISTANT⟧\n' + narration + '\n')
    got = explicit_confirmation(s, target(s))
    assert (got.status, got.value) == ('RESOLVED', True)
    s = store(response='⟦ASSISTANT⟧\n' + narration + '\n→ TOOL_CALL apply_a: {"record_id":"X","amount":2}',
              extra='⟦ASSISTANT⟧\nConfirm apply_a: {"record_id":"X","amount":2}?\n⟦USER⟧\nДа\n')
    assert explicit_confirmation(s, target(s)).value is True


def test_narration_after_read_call_stays_unknown_and_never_false():
    s = store('⟦ASSISTANT⟧\nConfirm apply_a: {"record_id":"X","amount":2}?\n⟦USER⟧\nYes\n⟦ASSISTANT⟧\n→ TOOL_CALL inspect_b: {"record_id":"X"}\n'
              '← TOOL_RESPONSE inspect_b: {"record_id":"X"}\n⟦ASSISTANT⟧\nI will apply the action to X now.\n')
    got = explicit_confirmation(s, target(s))
    assert got.status == 'UNRESOLVED' and got.value is None


def test_refusal_then_new_bound_question_without_reply_is_false_only_when_never_answered():
    # Latest reply is a refusal to the latest answered bound question.
    s = store('⟦ASSISTANT⟧\nConfirm apply_a: {"record_id":"X","amount":2}?\n⟦USER⟧\nNo\n⟦ASSISTANT⟧\nI will call apply_a: {"record_id":"X","amount":2}\n')
    assert explicit_confirmation(s, target(s)).value is False
    # Description and call with no user turn at all after any bound description.
    s = store('⟦ASSISTANT⟧\nI will call apply_a: {"record_id":"X","amount":2}\n')
    assert explicit_confirmation(s, target(s)).reason == 'NO_USER_TURN_AFTER_BOUND_DESCRIPTION'


INFO = '⟦ASSISTANT⟧\nWhich record?\n⟦USER⟧\nRecord X, please.\n'


@pytest.mark.parametrize('question', ['Do you confirm the action on X? Please answer «yes».',
    'Подтверждаете ли вы действие для X?', 'Shall I proceed with X?'])
def test_unanswered_bound_confirmation_question_is_false_when_never_affirmed(question):
    # Earlier bound text got a non-confirming user reply, then a confirmation question nobody answered.
    s = store('⟦ASSISTANT⟧\nRecord X has amount 1. What would you like?\n⟦USER⟧\nChange it to 2.\n'
              '⟦ASSISTANT⟧\n' + question + '\n')
    got = explicit_confirmation(s, target(s))
    assert (got.status, got.value) == ('UNRESOLVED', None)  # No operation/parameter certificate in this prose.


@pytest.mark.parametrize('text', ['Thanks for confirming, I will apply the action to X now?',
    'I will apply the action to X now.', 'Record X: amount 2. Anything else?'])
def test_unanswered_rule_needs_explicit_confirmation_question(text):
    s = store('⟦ASSISTANT⟧\nRecord X has amount 1. What would you like?\n⟦USER⟧\nChange it to 2.\n⟦ASSISTANT⟧\n' + text + '\n')
    assert explicit_confirmation(s, target(s)).value is not False


def test_repeated_question_after_earlier_affirmation_is_unknown():
    s = store('⟦ASSISTANT⟧\nConfirm apply_a: {"record_id":"X","amount":2}?\n⟦USER⟧\nYes\n⟦ASSISTANT⟧\nConfirm apply_a: {"record_id":"X","amount":2}?\n')
    got = explicit_confirmation(s, target(s))
    assert got.status == 'UNRESOLVED' and got.reason == 'later_unanswered_proposal_after_earlier_reply'
    # A question before an intervening read call does not count for the current segment.
    s = store('⟦ASSISTANT⟧\nRecord X: what next?\n⟦USER⟧\nHmm\n⟦ASSISTANT⟧\nConfirm apply_a: {"record_id":"X","amount":2}?\n'
              '→ TOOL_CALL inspect_b: {"record_id":"X"}\n← TOOL_RESPONSE inspect_b: {"record_id":"X"}\n')
    assert explicit_confirmation(s, target(s)).value is not False


@pytest.mark.parametrize('text,expected', [('The current time is 2024-05-15 15:00:00 EST', '2024-05-15T15:00:00-05:00'),
    ('The current time is 2024-05-15 15:00:00', None),
    ('The current time is 2024-05-15 15:00:00Z', '2024-05-15T15:00:00+00:00')])
def test_policy_time_explicit_timezone(text, expected):
    s = store(policy=text); value = current_datetime(s, target(s))
    assert value.value == expected
    assert value.status == ('RESOLVED' if expected else 'UNRESOLVED')


def test_latest_current_time_result_unknown_does_not_reuse_old_time():
    extra = '⟦ASSISTANT⟧\n→ TOOL_CALL get_current_time: {}\n← TOOL_RESPONSE get_current_time: "2024-01-01T00:00:00Z"\n'
    s = store(extra); assert current_datetime(s, target(s)).status == 'RESOLVED'
    s = store(extra + '→ TOOL_CALL get_current_time: {}\n← TOOL_RESPONSE get_current_time: "2024-02-01T00:00:00"\n')
    assert current_datetime(s, target(s)).status == 'UNRESOLVED'


def test_current_time_plaintext_tool_and_long_explicit_affirmation():
    s = store('⟦ASSISTANT⟧\n→ TOOL_CALL get_current_time: {}\n← TOOL_RESPONSE get_current_time: The current time is 2025-11-14 03:40:00 EST.\n')
    assert current_datetime(s, target(s)).value == '2025-11-14T03:40:00-05:00'
    s = store('⟦ASSISTANT⟧\nConfirm apply_a: {"record_id":"X","amount":2}?\n⟦USER⟧\nYes, I confirm the action. Thank you for explaining the details so clearly and checking everything in advance.\n')
    assert explicit_confirmation(s, target(s)).status == 'UNRESOLVED'  # Uninspected free-text reply tail.


def test_forbidden_empty_collection_does_not_emit_and_prior_binding_rejects_other_entity():
    s = store('⟦ASSISTANT⟧\n→ TOOL_CALL inspect_b: {"record_id":"Y"}\n← TOOL_RESPONSE inspect_b: {"values":[]}\n')
    a = atomic(modality='FORBIDS', confirmation=None, condition=comparison('state.inspect_b./values/*', value=True, quantifier='ANY'))
    assert not evaluate_atom(s, a, target(s))['finding']
    a = atomic(modality='REQUIRES_PRIOR_CALL', confirmation=None, prior_call='inspect_b', binding={'argument': 'record_id', 'record_field': 'record_id'})
    assert evaluate_atom(s, a, target(s))['finding']


def test_type_difference_null_and_temporal_unknown_zone():
    s = store()
    for expr in [comparison(value=True), comparison('args.amount', op='<', value='2')]:
        a = atomic(modality='REQUIRES', confirmation=None, condition=expr)
        assert not evaluate_atom(s, a, target(s))['finding']
    assert evaluate_atom(s, atomic(modality='REQUIRES', confirmation=None, condition=comparison(value=None)), target(s))['value'] == 'FALSE'
    a = atomic(modality='REQUIRES', confirmation=None, condition=comparison('ctx.current_datetime', op='before', value='2024-01-01T00:00:00Z'))
    assert evaluate_atom(s, a, target(s))['value'] == 'UNRESOLVED'


def test_real_catalogs_compact_and_ID_free_without_gold():
    root = Path(__file__).resolve().parents[1]
    groups = {}
    for line in (root / 'outputs/searh_23/source_search_20261002/comparison_ids_v5/inputs.jsonl').read_text(encoding='utf-8').splitlines():
        s = SourceStore(json.loads(line)); groups.setdefault(policy_hash(s), []).append(s)
    assert len(groups) == 4
    import re
    for stores in groups.values():
        cat = normalize_catalog(stores)
        assert len(cat['paths']) <= 120
        assert not any(re.search(r'\d{4}', p) for p in cat['paths'] if p.startswith('state.'))
        assert all(f['witness']['kind'] == 'DECLARATION' for t in cat['tools'].values() for f in t['arguments'].values())


def test_request_does_not_mutate_declaration_witness():
    s = store(); p = policy(s); before = json.dumps(p, sort_keys=True)
    request(p, {'kind': 'TOOL_CALL', 'tool': 'apply_a'})
    assert json.dumps(p, sort_keys=True) == before


@pytest.mark.parametrize('quantifier,values,expected', [('ANY', [], 'UNRESOLVED'), ('ALL', [], 'UNRESOLVED'),
    ('ANY', [False], 'FALSE'), ('ALL', [True], 'TRUE'), ('ANY', [False, True, False], 'TRUE'),
    ('ALL', [True, True, False], 'FALSE')])
def test_quantifiers_empty_one_three(quantifier, values, expected):
    s = store('⟦ASSISTANT⟧\n→ TOOL_CALL inspect_b: {"record_id":"X"}\n← TOOL_RESPONSE inspect_b: ' + json.dumps({'record_id': 'X', 'values': values}) + '\n')
    a = atomic(modality='REQUIRES', confirmation=None, condition=comparison('state.inspect_b./values/*', value=True, quantifier=quantifier))
    assert evaluate_atom(s, a, target(s))['value'] == expected


def test_TARGET_missing_binding_rejected_and_same_entity_only():
    s = store('⟦ASSISTANT⟧\n→ TOOL_CALL inspect_b: {"record_id":"X"}\n← TOOL_RESPONSE inspect_b: {"records":{"X":{"record_id":"X","enabled":true},"Y":{"record_id":"Y","enabled":false}}}\n')
    p = policy(s); path = 'state.inspect_b./records/{key}/enabled'
    a = atomic(modality='REQUIRES', confirmation=None, condition=comparison(path, value=True, quantifier='TARGET'))
    assert admit({'atoms': [a.model_dump()]}, p, {'kind': 'TOOL_CALL', 'tool': 'apply_a'})['discarded'][0]['reason'] == 'TARGET_requires_binding'
    a.condition.binding = __import__('guardian_truth.policy_table_v11.schema', fromlist=['Binding']).Binding(argument='record_id', record_field='$key')
    assert evaluate_atom(s, a, target(s))['value'] == 'TRUE'
    assert evaluate_atom(s, a, {**target(s), 'arguments': {'record_id': 'Z', 'amount': 2}})['value'] == 'UNRESOLVED'


def test_ANY_OF_orders_match_extra_atom_and_clauses_do_not_break_agreement():
    s = store(policy='1. Before action number must be 2.\n2. Number may be 3.')
    p = policy(s); trigger = {'kind': 'TOOL_CALL', 'tool': 'apply_a'}
    a = atomic(modality='REQUIRES', confirmation=None, condition={'kind': 'ANY_OF', 'items': [comparison(value=2), comparison(value=3)]})
    b = a.model_copy(deep=True); b.clause_ids = ['clause_1']; b.condition.items.reverse()
    assert canonical(p['policy_sha256'], trigger, a) == canonical(p['policy_sha256'], trigger, b)
    proposals = [{'proposer': str(i), 'family': ['one', 'two', 'one'][i], 'trigger': trigger,
        'response': {'atoms': [obj.model_dump()] + ([atomic().model_dump()] if i == 0 else [])}} for i, obj in enumerate([a, b, a])]
    table = assemble(p, proposals)
    assert len(table['atoms']) == 1 and table['atoms'][0]['status'] == 'DECISIVE'
    assert table['atoms'][0]['atom']['clause_ids'] == ['clause_0', 'clause_1']
    verify_table(table)
    table['atoms'][0]['status'] = 'SHADOW'
    with pytest.raises(ValueError): verify_table(table)


@pytest.mark.parametrize('left,right', [(comparison(op='in', value=[2]), comparison(value=2.0)),
    (comparison(op='!=', value=2), comparison(op='not_in', value=[2.0])),
    (comparison(op='in', value=[2, 3]), comparison(op='in', value=[3.0, 2.0]))])
def test_decimal_membership_normalization(left, right):
    s = store(); p = policy(s); trigger = {'kind': 'TOOL_CALL', 'tool': 'apply_a'}
    a = atomic(modality='REQUIRES', confirmation=None, condition=left)
    b = atomic(modality='REQUIRES', confirmation=None, condition=right)
    assert canonical(p['policy_sha256'], trigger, a) == canonical(p['policy_sha256'], trigger, b)


def test_union_exception_of_invalid_atom_suppresses_other_accepted_atom():
    s = store('⟦ASSISTANT⟧\nConfirm apply_a: {"record_id":"X","amount":2}?\n'); p = policy(s); tr = {'kind': 'TOOL_CALL', 'tool': 'apply_a'}
    a = atomic().model_dump()
    invalid = {**a, 'modality': 'REQUIRES', 'confirmation': None, 'condition': comparison('args.nonexistent'),
        'exceptions': [comparison(value=2)]}
    proposals = [{'proposer': str(i), 'family': str(i), 'trigger': tr, 'response': {'atoms': [a] + ([invalid] if i == 0 else [])}} for i in range(3)]
    table = assemble(p, proposals)
    assert len(table['atoms']) == 1 and len(table['atoms'][0]['atom']['exceptions']) == 1
    result = evaluate_table(s, table)
    assert not result['decisive_error'] and result['trace'][0]['suppressed']


def test_unknown_exception_and_unknown_confirmation_cannot_emit_error():
    s = store(); a = atomic()
    assert not evaluate_atom(s, a, target(s))['finding']
    s = store('⟦ASSISTANT⟧\nConfirm apply_a: {"record_id":"X","amount":2}?\n')
    assert evaluate_atom(s, a, target(s))['finding']
    a.exceptions = [Expression.model_validate(comparison('args.unknown', value=2))]
    assert not evaluate_atom(s, a, target(s))['finding']


def test_multiple_TARGET_records_latest_missing_and_later_response_calls():
    base = '⟦ASSISTANT⟧\n→ TOOL_CALL inspect_b: {"record_id":"X"}\n← TOOL_RESPONSE inspect_b: {"records":[{"record_id":"X","enabled":false},{"record_id":"X","enabled":false}]}\n'
    s = store(base)
    a = atomic(modality='REQUIRES', confirmation=None, condition=comparison('state.inspect_b./records/*/enabled', value=True,
        quantifier='TARGET', binding={'argument': 'record_id', 'record_field': 'record_id'}))
    assert evaluate_atom(s, a, target(s))['value'] == 'UNRESOLVED'
    s = store(base + '→ TOOL_CALL inspect_b: {"record_id":"X"}\n← TOOL_RESPONSE inspect_b: {"records":[]}\n')
    assert not evaluate_atom(s, a, target(s))['finding']
    s = store(response='⟦ASSISTANT⟧\nConfirm apply_a: {"record_id":"X","amount":2}?\n→ TOOL_CALL apply_a: {"record_id":"X","amount":2}')
    assert evaluate_atom(s, atomic(), target(s))['finding']


def test_state_anchor_uses_only_identifiers_the_read_tool_was_called_with():
    # Regression: payment_method_id-style target identifiers absent from the read record must not
    # make a same-entity scalar state permanently UNRESOLVED.
    read = '⟦ASSISTANT⟧\n→ TOOL_CALL inspect_b: {"record_id":"X"}\n← TOOL_RESPONSE inspect_b: {"record_id":"X","status":"open"}\n'
    a = atomic(modality='REQUIRES', confirmation=None, condition=comparison('state.inspect_b./status', value='open'))
    s = store(read, response='→ TOOL_CALL apply_a: {"record_id":"X","account_id":"P1","amount":2}')
    assert evaluate_atom(s, a, target(s))['value'] == 'TRUE'
    # Another entity stays excluded, and a later read of a different record does not leak.
    s = store(read, response='→ TOOL_CALL apply_a: {"record_id":"Y","account_id":"P1","amount":2}')
    assert evaluate_atom(s, a, target(s))['value'] == 'UNRESOLVED'
    s = store(read + '→ TOOL_CALL inspect_b: {"record_id":"Y"}\n← TOOL_RESPONSE inspect_b: {"record_id":"Y","status":"closed"}\n',
              response='→ TOOL_CALL apply_a: {"record_id":"X","account_id":"P1","amount":2}')
    assert evaluate_atom(s, a, target(s))['value'] == 'TRUE'
