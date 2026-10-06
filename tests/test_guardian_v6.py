"""Unit tests for the v6 mechanical layers (synthetic packets, no network)."""
import json

from guardian_truth.v6 import provenance as P, structural as S, turnrules as F
from guardian_truth.v6 import decide as D


def pk(history=(), targets=(), policy='Be nice.', decl='[AVAILABLE TOOLS]\n- pay(payment_id)', complete=True, status=None):
    return dict(coverage=dict(complete_input=complete, declaration_status=status or {}),
                normative_sources=[dict(source_id='q1', text=policy)], declarations=[dict(source_id='q2', text=decl)],
                history=list(history), current_targets=list(targets))


def call(sid, tool, args, role='assistant'):
    return dict(source_id=sid, role=role, kind='call', tool=tool, text=f'\t→ TOOL_CALL {tool}: {json.dumps(args)}')


def res(sid, tool, text):
    return dict(source_id=sid, role='assistant', kind='result', tool=tool, text=f'\t← TOOL_RESPONSE {tool}: {text}')


def user(sid, text):
    return dict(source_id=sid, role='user', kind='text', tool=None, text=text)


def test_turnrules_check_counts_calls_and_text():
    rules = [dict(type='MAX_TOOL_CALLS_PER_TURN', n=1, quote='one tool call at a time', source_id='q1'),
             dict(type='NO_TEXT_WITH_TOOL_CALL', n=None, quote='not both', source_id='q1')]
    t = [call('t0', 'a', {}), call('t1', 'b', {})]
    assert [c['kind'] for c in F.check(rules, t)] == ['MAX_TOOL_CALLS_PER_TURN']
    t2 = [dict(source_id='t0', kind='text', text='Done!'), call('t1', 'b', {})]
    assert [c['kind'] for c in F.check(rules, t2)] == ['NO_TEXT_WITH_TOOL_CALL']
    assert F.check(rules, [call('t0', 'a', {})]) == []
    assert F.check([], t) == []                       # no extracted rule -> nothing, never assumed


def test_turnrules_extract_requires_verbatim_quote_and_agreement(monkeypatch):
    pol = [dict(source_id='q1', text='You should only make one tool call at a time.\nOther text.')]
    answers = iter([{'rules': [dict(type='MAX_TOOL_CALLS_PER_TURN', n=1, quote='You should only make one tool call at a time'),
                               dict(type='NO_TEXT_WITH_TOOL_CALL', n=None, quote='never talk while calling tools')]},
                    {'rules': [dict(type='MAX_TOOL_CALLS_PER_TURN', n=1, quote='You should only make one tool call at a time')]}])
    monkeypatch.setattr(F, 'call', lambda client, req, attempt, tag: ({'content': 'x'}, next(answers), None))
    monkeypatch.setattr(F, 'step_record', lambda *a: {})
    rules, meta = F.extract(None, 'm', pol)
    assert [(r['type'], r['n']) for r in rules] == [('MAX_TOOL_CALLS_PER_TURN', 1)]   # invented quote dropped


def test_provenance_flags_invented_identifier_only():
    h = [user('h0', 'My email is ann.lee3019@x.com'), res('h1', 'get_user', '{"payment_methods": ["paypal_77"]}')]
    p = pk(h, [call('t0', 'find_user', {'zip': '3019', 'payment_id': 'paypal_77'})])
    out = P.check(p)
    assert len(out) == 1 and out[0]['values'] == [('zip', '3019')]


def test_provenance_ignores_declaration_examples_but_accepts_user_values():
    decl = "- pay(payment_id): the id, such as 'gift_card_0000000' or 'credit_card_0000000'."
    assert P.check(pk([user('h0', 'hi')], [call('t0', 'pay', {'payment_id': 'credit_card_0000000'})], decl=decl))
    assert not P.check(pk([user('h0', 'use credit_card_0000000')], [call('t0', 'pay', {'payment_id': 'credit_card_0000000'})], decl=decl))


def test_provenance_not_from_agents_own_text_and_needs_complete_input():
    h = [dict(source_id='h0', role='assistant', kind='text', text='I will use zip 99881'), user('h1', 'ok')]
    t = [call('t0', 'find', {'zip': '99881'})]
    assert P.check(pk(h, t))                          # the agent's own earlier prose is not provenance
    assert not P.check(pk(h, t, complete=False))      # incomplete packet: absence is never evidence


def test_provenance_word_slug_and_numbers_not_flagged():
    t = [call('t0', 'book', {'job': 'brake_pads_front', 'amount': 120, 'count': '2', 'date': '2024-05-01'})]
    assert not P.check(pk([user('h0', 'please fix the brakes')], t))
    t = [call('t0', 'close', {'account_id': 'blue_account_placeholder'})]
    assert P.check(pk([user('h0', 'close my blue account')], t))


def test_structural_repeat_failed_and_undeclared():
    c = {'name': 'x'}
    h = [call('h0', 'find', c), res('h1', 'find', 'Error: user not found'), user('h2', 'try again')]
    out = S.hypotheses(pk(h, [call('t0', 'find', c)]))
    assert [o['kind'] for o in out] == ['REPEAT_FAILED_CALL']
    h_ok = [call('h0', 'find', c), res('h1', 'find', '{"id": 1}')]
    assert S.hypotheses(pk(h_ok, [call('t0', 'find', c)])) == []
    out = S.hypotheses(pk([], [call('t0', 'device_check', {})], status={'device_check': 'UNDECLARED_IN_COMPLETE_PARSED_CATALOG'}))
    assert [o['kind'] for o in out] == ['UNDECLARED_TOOL']
    assert S.hypotheses(pk([], [call('t0', 'z', {})], status={'z': 'NOT_FOUND_IN_UNVERIFIED_CATALOG'})) == []


def test_decide_priority_and_certificate(monkeypatch):
    monkeypatch.setattr(D, 'decide_v5', lambda rec: (0, None))
    f = dict(origin='F', kind='MAX_TOOL_CALLS_PER_TURN', target_id='t1', reason='two calls')
    p = dict(origin='P', kind='UNSOURCED_ARGUMENT', target_id='t0', reason='invented id')
    d, acc = D.decide_v6({}, [p, f])
    assert d == 1 and acc['origin'] == 'F' and acc['certificate'] == 'MECHANICAL' and acc['findings'] == ['MAX_TOOL_CALLS_PER_TURN', 'UNSOURCED_ARGUMENT']
    monkeypatch.setattr(D, 'decide_v5', lambda rec: (1, dict(origin='A_adm2', text='x', target_id='t0')))
    d, acc = D.decide_v6({}, [])
    assert d == 1 and acc['certificate'] == 'MODEL'
