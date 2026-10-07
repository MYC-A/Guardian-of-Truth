"""Contrast tests for the typed consistency check (no model). Names/values are arbitrary; the same expression must
evaluate both polarities, and statuses must never claim more than the arithmetic/logic."""
from experiments.guardian_addons.evaluator import check, compute

SRC = {'p1': 'Moves above 1000.00 need approval, except between accounts of the same holder.',
       'h1': '{"account": "X-1", "holder": "kim_a"}', 'h2': '{"account": "Y-9", "holder": "kim_a"}', 'h3': '{"amount": "1500.00"}',
       'h4': '{"holder": "lee_b"}'}


def chk(owner2, claimed, owner2_src='h2'):
    # Evaluate the applicability predicate itself; IF/THEN was never a supported
    # boolean grammar and previously silently dropped the consequent.
    return dict(requirement_source_id='p1', expression='amount > 1000.00 AND src.holder != dst.holder',
                bindings=[dict(name='amount', value='1500.00', type='NUMBER', source_id='h3'),
                          dict(name='src.holder', value='kim_a', type='STRING', source_id='h1'),
                          dict(name='dst.holder', value=owner2, type='STRING', source_id=owner2_src)], claimed_result=claimed)


def test_same_holder_claimed_true_is_contradiction():
    r = check(chk('kim_a', 'TRUE'), SRC)
    assert r['consistency'] == 'CONTRADICTION' and r['computed'] == 'FALSE'
    assert r['interpretation'] == 'MODEL' and r['binding'] == 'MODEL'      # never promoted


def test_same_holder_claimed_false_consistent():
    assert check(chk('kim_a', 'FALSE'), SRC)['consistency'] == 'CONSISTENT'


def test_other_holder_both_polarities():
    assert check(chk('lee_b', 'TRUE', 'h4'), SRC)['consistency'] == 'CONSISTENT'
    assert check(chk('lee_b', 'FALSE', 'h4'), SRC)['consistency'] == 'CONTRADICTION'


def test_equal_display_names_are_strings_not_identity():
    # case differs -> different strings; code does not decide identity by case-folding
    assert compute("a == b", [dict(name='a', value='Kim A', type='STRING'), dict(name='b', value='kim a', type='STRING')]) == ('OK', False)


def test_source_status_separate_from_consistency():
    c = chk('kim_a', 'TRUE'); c['bindings'][2]['value'] = 'kim_z'                     # value absent from its cited source
    r = check(c, SRC)
    assert [s['status'] for s in r['source_status']] == ['VERBATIM', 'VERBATIM', 'NOT_FOUND']
    assert r['consistency'] == 'CONSISTENT'                                              # kim_a != kim_z -> TRUE as claimed


def test_unknown_claim_and_bad_inputs_are_unevaluable():
    assert check(chk('kim_a', 'UNKNOWN'), SRC)['consistency'] == 'UNEVALUABLE'
    assert check(dict(expression='amount > ', bindings=[], claimed_result='TRUE'), SRC)['computation'] == 'PARSE_ERROR'
    assert check(dict(expression='amount > 5', bindings=[], claimed_result='TRUE'), SRC)['computation'] == 'UNBOUND:amount'
    assert check(dict(expression="a > 'x'", bindings=[dict(name='a', value='3', type='NUMBER')], claimed_result='TRUE'), SRC)['computation'] == 'TYPE_ERROR'
    assert check(dict(expression='__import__("os")', bindings=[], claimed_result='TRUE'), SRC)['computation'] == 'PARSE_ERROR'


def test_dates_and_arithmetic():
    b = [dict(name='s', value='2025-06-02T08:00:00Z', type='DATETIME'), dict(name='e', value='2025-06-03T04:00:00Z', type='DATETIME')]
    assert compute('hours_between(s, e) > 24', b) == ('OK', False)
    b[1]['value'] = '2025-06-03T14:00:00Z'
    assert compute('hours_between(s, e) > 24', b) == ('OK', True)
    assert compute('base + fee == paid', [dict(name='base', value='60.00', type='NUMBER'), dict(name='fee', value='15', type='NUMBER'),
                                          dict(name='paid', value='75.0', type='NUMBER')]) == ('OK', True)
    assert compute('NOT (x = 1)', [dict(name='x', value='1', type='NUMBER')]) == ('OK', False)
