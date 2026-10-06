"""V4 unit tests (PROTOCOL §11, spec §28/§34): DF4 code-first checks, typed proof executor, all-target coverage,
CB user-actor, post-processing invariants. No model calls."""
import datetime as dt
import json

from guardian_truth.verification import alltarget, derived as D, df4, ems, proof
from guardian_truth.verification.confirm import is_affirmation
from guardian_truth.verification.v4 import decide_v4

ND = dt.date(2025, 4, 10)


def sc(text, nd=ND):
    return df4.self_checks('t0', text, nd, df4.extract(text, nd))


# ---------------- DF ----------------
def test_ru_en_dates_and_weekdays():
    assert D.parse_date('14 апреля', ND) == dt.date(2025, 4, 14)
    assert D.parse_date('April 14, 2025') == dt.date(2025, 4, 14)
    assert D.parse_date('14.04.2025') == dt.date(2025, 4, 14)
    assert D.parse_weekday('в среду') == 2 and D.parse_weekday('Wednesday') == 2


def test_weekday_adjacent_mismatch_and_match():
    r = sc('Ближайшая запись — в среду, 14 апреля, в 13:30.')
    assert r[0]['check'] == 'WEEKDAY_ADJACENT' and r[0]['status'] == 'MISMATCH' and r[0]['computed'] == 'Monday'
    assert sc('Wednesday, April 16 works')[0]['status'] == 'MATCH'
    assert sc('понедельник 14 апреля и во вторник 15 апреля')[1]['status'] == 'MATCH'


def test_leap_and_boundaries():
    assert D.parse_date('29 февраля 2024') == dt.date(2024, 2, 29)
    assert D.parse_date('29 февраля 2025') is None
    assert sc('Thursday, February 29, 2024')[0]['status'] == 'MATCH'
    assert D.add_business_days(dt.date(2024, 12, 31), 1) == dt.date(2025, 1, 1)


def test_range_nights():
    assert sc('Проживание с 10 по 15 октября (5 ночей)')[0]['status'] == 'MATCH'
    r = sc('Booking 10-14 May, 5 nights')
    assert r[0]['check'] == 'RANGE_NIGHTS' and r[0]['status'] == 'MISMATCH' and r[0]['computed'] == 4


def test_business_days():
    fri = dt.date(2025, 3, 14)
    assert D.next_business_day(fri) == dt.date(2025, 3, 17)
    assert D.add_business_days(fri, 3) == dt.date(2025, 3, 19)
    assert D.add_business_days(dt.date(2025, 3, 15), 1) == dt.date(2025, 3, 17)    # weekend start


def test_inline_arithmetic_and_decimal_separators():
    assert sc('Итого: 2.5 h × 64 EUR + 118 EUR = 278 EUR.')[0]['status'] == 'MATCH'
    assert sc('Итого: 2,5 ч × 64 € + 118 € = 288 €')[0]['status'] == 'MISMATCH'
    assert sc('Стоимость 12 × 87.50 = 1 050 EUR')[0]['status'] == 'MATCH'
    r = sc('12 × 87,50 = 1040 €')
    assert r[0]['status'] == 'MISMATCH' and r[0]['computed'] == 1050
    assert D.parse_number('1 050,00') == 1050 and D.parse_number('1,050.00') == 1050
    assert all(c['kind'] != 'date' for c in df4.extract('2.5 h × 64 EUR', ND))     # '2.5' is not 2 May


def _packet(texts):
    p = dict(normative_sources=[], history=[], declarations=[], current_targets=[])
    for sid, t in texts.items():
        k = 'normative_sources' if sid.startswith('q') else 'current_targets' if sid.startswith('t') else 'history'
        p[k].append(dict(source_id=sid, text=t, kind='call' if 'TOOL_CALL' in t else 'text', role='assistant'))
    return p


def test_binder_operand_value_comes_from_quote_not_model():
    texts = {'q1': 'The current time is 2025-03-13 10:00. Port-out completes in 3 business days.', 't0': 'завершится 18 марта'}
    claim = dict(kind='date', value=dt.date(2025, 3, 18), span='18 марта')
    b = dict(operation='ADD_BUSINESS_DAYS', expression='', operands=[
        dict(name='date', source_id='q1', quote='The current time is 2025-03-13 10:00', value='2025-03-14'),   # pre-shifted by the model
        dict(name='n', source_id='q1', quote='completes in 3 business days', value='3')])
    nonmove = {'q1': texts['q1']}
    r = df4.evaluate_binding(b, claim, texts, dt.date(2025, 3, 13), {'t0'}, nonmove)
    assert r['status'] == 'MATCH' and r['computed'] == '2025-03-18'           # 13 Mar + 3 bd, the model's shift ignored
    b['operands'][0]['quote'] = 'current time is 2025-03-12'                   # not verbatim -> UNVERIFIED
    assert df4.evaluate_binding(b, claim, texts, dt.date(2025, 3, 13), {'t0'}, nonmove)['status'] == 'UNVERIFIED'
    b2 = dict(b, operation='WEEKDAY_OF')
    assert df4.evaluate_binding(b2, claim, texts, ND, {'t0'}, nonmove)['note'] == 'OPERATION_KIND_MISMATCH'


# ---------------- multi-source proof ----------------
T0 = '\t→ TOOL_CALL transfer: {"from_account": "ACC-1", "payee_id": "PY-118", "amount_eur": 400}'
T1 = '\t→ TOOL_CALL transfer: {"from_account": "ACC-1", "payee_id": "PY-181", "amount_eur": 900}'
H4 = '\t← TOOL_RESPONSE get_customer: {"customer_no": "C-1", "daily_payee_limit_eur": 1000, "transfers_today": []}'
TX = dict(q7='The total of transfers to payees on one calendar day may not exceed the customer\'s `daily_payee_limit_eur`.', h4=H4, t0=T0, t1=T1)


def plan(op='SUM_COMPARE_LE', **over):
    ops = [dict(role='term', source_id='t0', quote='"amount_eur": 400', value='400', type='number'),
           dict(role='term', source_id='t1', quote='"amount_eur": 900', value='900', type='number'),
           dict(role='bound', source_id='h4', quote='{"customer_no": "C-1", "daily_payee_limit_eur": 1000, "transfers_today": []}', value='1000', type='number')]
    p = dict(operation=op, target_ids=['t0', 't1'], operands=ops)
    p.update(over)
    return p


def ex(p, texts=TX):
    return proof.execute(p, texts, ['t0', 't1'])


def test_400_plus_900_exceeds_1000():
    r = ex(plan())
    assert r['status'] == 'VIOLATED' and '1300' in r['detail']


def test_comparison_direction():
    assert ex(plan('SUM_COMPARE_GE'))['status'] == 'HOLDS'
    assert ex(plan('SUM_COMPARE_LT'))['status'] == 'VIOLATED'


def test_valid_multi_source_no_error():
    texts = dict(TX, h4=H4.replace('1000', '2000'))
    p = plan()
    p['operands'][2] = dict(p['operands'][2], quote='"daily_payee_limit_eur": 2000', value='2000')
    assert ex(p, texts)['status'] == 'HOLDS'


def test_source_missing_wrong_quote_wrong_id_wrong_parse():
    p = plan(); p['operands'][2] = dict(p['operands'][2], source_id='h9')
    assert ex(p)['note'] == 'SOURCE_MISSING'
    p = plan(); p['operands'][0] = dict(p['operands'][0], quote='"amount_eur": 4000')
    assert ex(p)['note'] == 'QUOTE_NOT_VERIFIED'
    p = plan(); p['operands'][0] = dict(p['operands'][0], source_id='t1')
    assert ex(p)['status'] == 'UNRESOLVED'
    p = plan(); p['operands'][1] = dict(p['operands'][1], value='nine hundred')
    assert ex(p)['note'] == 'VALUE_NOT_PARSED'
    p = plan(); p['operands'][1] = dict(p['operands'][1], value='950')
    assert ex(p)['note'] == 'VALUE_NOT_IN_QUOTE'


def test_one_target_absent_and_duplicate_operand():
    p = plan(); p['operands'] = [o for o in p['operands'] if o['source_id'] != 't0' and o['source_id'] != 't1'] + [
        dict(role='term', source_id='h4', quote='"daily_payee_limit_eur": 1000', value='1000', type='number')]
    assert ex(p)['status'] == 'UNRESOLVED'
    p = plan(); p['operands'].append(dict(p['operands'][0]))
    assert ex(p)['note'] == 'DUPLICATE_OPERAND'
    assert ex(plan(target_ids=['t5']))['note'] == 'BAD_TARGET_IDS'


def test_other_ops():
    texts = dict(h2='\t← TOOL_RESPONSE get_order: {"address": "Tamme 5"}', h6='\t← TOOL_RESPONSE update: {"address": "Kase 9"}',
                 t0='\t→ TOOL_CALL ship: {"address": "Tamme 5"}', q1='Allowed cabins: economy, business.')
    p = dict(operation='LATEST_VALUE_EQ', target_ids=['t0'], operands=[
        dict(role='value', source_id='t0', quote='"address": "Tamme 5"', value='Tamme 5', type='string'),
        dict(role='observed', source_id='h2', quote='"address": "Tamme 5"', value='Tamme 5', type='string'),
        dict(role='observed', source_id='h6', quote='"address": "Kase 9"', value='Kase 9', type='string')])
    r = proof.execute(p, texts, ['t0'])
    assert r['status'] == 'VIOLATED' and 'h6' in r['detail']
    t = dict(t0='\t→ TOOL_CALL book: {"date": "2025-03-17"}', q1='The current time is 2025-03-14 09:00.')
    p = dict(operation='AFTER', target_ids=['t0'], operands=[dict(role='left', source_id='t0', quote='"date": "2025-03-17"', value='2025-03-17', type='date'),
                                                              dict(role='right', source_id='q1', quote='2025-03-14 09:00', value='2025-03-14', type='date')])
    assert proof.execute(p, t, ['t0'])['status'] == 'HOLDS'


def test_unverifiable_leaf_never_violated():
    p = plan(); p['operands'][2] = dict(p['operands'][2], quote='limit 1000 EUR')
    assert ex(p)['status'] == 'UNRESOLVED'


# ---------------- all-target ----------------
TP = _packet(dict(q1='Transfers may not exceed the daily limit of 1000 EUR.', h1='limit 1000', t0=T0, t1=T1))


def item(t, s, q='Transfers may not exceed the daily limit of 1000 EUR.', ev=None):
    return dict(target_id=t, status=s, policy_source_ids=['q1'] if s == 'ERROR' else [], policy_quote=q if s == 'ERROR' else '',
                evidence=ev if ev is not None else ([dict(source_id=t, quote='"amount_eur": 900' if t == 't1' else '"amount_eur": 400')] if s == 'ERROR' else []),
                reason='')


def test_at_t0_ok_t1_error():
    cov, rows, cand = alltarget.assess(dict(targets=[item('t0', 'NO_ERROR'), item('t1', 'ERROR')]), TP)
    assert cov['complete'] and cand['target_id'] == 't1'


def test_at_t0_error_t1_ok_and_both_ok():
    assert alltarget.assess(dict(targets=[item('t0', 'ERROR'), item('t1', 'NO_ERROR')]), TP)[2]['target_id'] == 't0'
    assert alltarget.assess(dict(targets=[item('t0', 'NO_ERROR'), item('t1', 'NO_ERROR')]), TP)[2] is None


def test_at_incomplete_never_error():
    for items in ([item('t1', 'ERROR')], [item('t0', 'NO_ERROR'), item('t0', 'NO_ERROR'), item('t1', 'ERROR')],
                  [item('t0', 'NO_ERROR'), item('t1', 'ERROR'), item('t2', 'NO_ERROR')]):
        cov, rows, cand = alltarget.assess(dict(targets=items), TP)
        assert not cov['complete'] and cand is None


def test_at_prose_plus_tool_and_three_calls():
    p = _packet(dict(q1='Transfers may not exceed the daily limit of 1000 EUR.', t0=T0, t1='Готово, оба перевода выполнены.', t2=T1))
    p['current_targets'][1]['kind'] = 'text'
    cov, rows, cand = alltarget.assess(dict(targets=[item('t0', 'NO_ERROR'), item('t1', 'NO_ERROR'), item('t2', 'ERROR', ev=[dict(source_id='t2', quote='"amount_eur": 900')])]), p)
    assert cov['complete'] and cand['target_id'] == 't2'
    cov, _, cand = alltarget.assess(dict(targets=[item('t0', 'NO_ERROR'), item('t2', 'ERROR')]), p)
    assert cov['missing'] == ['t1'] and cand is None


def test_at_unverified_evidence_not_admitted():
    cov, rows, cand = alltarget.assess(dict(targets=[item('t0', 'NO_ERROR'), item('t1', 'ERROR', ev=[dict(source_id='t1', quote='amount 950')])]), TP)
    assert cand is None


# ---------------- triggers / CB ----------------
def test_t_quant_trigger():
    p = _packet(dict(q1='The daily limit is 1000 EUR; transfers may not exceed it.', t0=T0))
    p['current_targets'][0]['kind'] = 'call'
    assert ems.trigger(p)['quant']
    p2 = _packet(dict(q1='Be polite.', t0=T0))
    p2['current_targets'][0]['kind'] = 'call'
    assert not ems.trigger(p2)['quant']


def test_cb_affirmation_text():
    assert is_affirmation('Да, оба.') and is_affirmation('yes please') and not is_affirmation('Да, но лучше завтра')


# ---------------- post-processing invariants ----------------
def _rec(**comps):
    r = dict(A=dict(guard_error=False, reasons=[]), A_adm2=dict(decision='NO_ERROR'))
    r.update(comps)
    return r


def test_structured_proof_survives_and_mechanical_arm():
    c = dict(candidate=dict(origin='Ems', kind='STRUCTURED_PROOF', code_proven=True, target_id='t1', requirement='r', reason='x'),
             verify=dict(verdict='UNRESOLVED'))
    d = decide_v4(_rec(Ems=c))
    assert d['A_Ems'][0] == 0 and d['A_Ems_mech'][0] == 1 and d['V4_mechanical'][0] == 1 and d['V4_raw'][0] == 1


def test_at_candidate_not_lost_to_t0_ownership():
    c = dict(candidate=dict(origin='AT', target_id='t1', requirement='r', reason='x'), verify=dict(verdict='SUPPORTED'))
    d = decide_v4(_rec(AT=c))
    assert d['A_AT'] == (1, d['A_AT'][1]) and d['A_AT'][1]['target_id'] == 't1' and d['V4'][0] == 1


def test_parse_failure_never_error():
    d = decide_v4(_rec(DF4=dict(admission='INVALID_JSON', candidate=None), Ems=dict(admission='ADMITTED', candidate=None)))
    assert all(v[0] == 0 for v in d.values())


# ---------------- dev fixes (logged in RESULTS.md, dev iteration 1) ----------------
def test_empty_list_term_is_zero():
    p = plan(); p['operands'].insert(0, dict(role='term', source_id='h4', quote='"transfers_today": []', value='0', type='number'))
    assert ex(p)['status'] == 'VIOLATED'


def test_verifier_multi_piece_evidence():
    from guardian_truth.verification.common import quote_q2
    from guardian_truth.verification.verifier import pieces_ok
    q = '→ TOOL_CALL transfer: {"from_account": "ACC-1", "payee_id": "PY-118", "amount_eur": 400}\n→ TOOL_CALL transfer: {"from_account": "ACC-1", "payee_id": "PY-181", "amount_eur": 900}'
    assert not quote_q2(q, [T0, T1]) and pieces_ok(q, [T0, T1], quote_q2)
    assert not pieces_ok(q.replace('900', '950'), [T0, T1], quote_q2)


def test_binder_role_mapping_by_type():
    texts = {'q1': 'The current time is 2025-03-13 10:00. Port-out takes 3 business days.'}
    claim = dict(kind='date', value=dt.date(2025, 3, 17), span='17 марта')
    b = dict(operation='ADD_BUSINESS_DAYS', expression='', operands=[
        dict(name='current_date', source_id='q1', quote='The current time is 2025-03-13 10:00', value='2025-03-13'),
        dict(name='business_days', source_id='q1', quote='Port-out takes 3 business days', value='3')])
    r = df4.evaluate_binding(b, claim, texts, dt.date(2025, 3, 13), {'t0'}, texts)
    assert r['status'] == 'MISMATCH' and r['computed'] == '2025-03-18'


def test_inline_result_before_expression_and_parentheses():
    assert sc('Доплата составит $100: (67 − 42) × 4 дня.')[0]['status'] == 'MATCH'
    assert sc('Доплата составит $110: (67 − 42) × 4 дня.')[0]['status'] == 'MISMATCH'
    assert sc('Итого (2 + 3) × 10 = 50 EUR')[0]['status'] == 'MATCH'


def test_polarity_check():
    up = dict(policy_quote='Declared value may not exceed 2,000 EUR per parcel.', requirement='')
    assert ems.polarity_error('GT', up) and ems.polarity_error('SUM_COMPARE_GE', up)
    assert ems.polarity_error('LE', up) is None and ems.polarity_error('EQ', up) is None
    lo = dict(policy_quote='Passengers must be at least 18 years old.', requirement='')
    assert ems.polarity_error('LT', lo) and ems.polarity_error('GE', lo) is None


def test_copied_claim_value_is_not_derived():
    claim = dict(kind='date', value=dt.date(2025, 4, 14), span='14 апреля')
    texts = {'q1': 'The current time is 2025-04-10 09:00.'}
    b = dict(operation='NEXT_BUSINESS_DAY', expression='', operands=[dict(name='date', source_id='q1', quote='The current time is 2025-04-10 09:00', value='2025-04-10')])
    res = ['\t← TOOL_RESPONSE get_slots: {"date": "2025-04-14", "slots": ["13:30"]}']
    assert df4.evaluate_binding(b, claim, texts, ND, {'t0'}, texts, res)['note'] == 'CLAIM_VALUE_IN_TOOL_RESULT'
    assert df4.evaluate_binding(b, claim, texts, ND, {'t0'}, texts, [])['status'] == 'MISMATCH'


def test_forward_operation_cannot_explain_earlier_claim():
    claim = dict(kind='date', value=dt.date(2025, 9, 25), span='25 сентября')
    texts = {'h11': '\t← TOOL_RESPONSE get_event: {"start": "2025-09-27T19:30"}'}
    b = dict(operation='NEXT_BUSINESS_DAY', expression='', operands=[dict(name='date', source_id='h11', quote='"start": "2025-09-27T19:30"', value='2025-09-27T19:30')])
    assert df4.evaluate_binding(b, claim, texts, ND, {'t0'}, texts)['note'] == 'DIRECTION_IMPLAUSIBLE'
