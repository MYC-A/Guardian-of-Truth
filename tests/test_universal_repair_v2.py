"""Audit probes (docs/independent_repair_review_20261006/agent_code_probes.py) inverted into
expected-correct contracts. Offline, no network."""
import datetime as dt
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    'audit_probes', ROOT / 'docs/independent_repair_review_20261006/agent_code_probes.py')
P = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(P)
from guardian_truth.repair import df5, evidence as E, proof5, v5, sourcejson
from guardian_truth.verification.proof import texts_of
leaf, packet = P.leaf, P.packet


def not_certified(case):
    c = case['ems_candidate']
    assert not case['certificate']
    assert c is None or not c.get('certificate')
    assert case['final_on_unresolved_verifier'] in (None, dict(ordinary=0, mechanical=0))


def test_empty_member_array_no_crash_and_violated():
    row, p = packet('The requested category must be in the allowed list.',
        '\u2190 TOOL_RESPONSE categories: {"allowed":[]}', '\u2192 TOOL_CALL select: {"category":"boxing"}')
    pl = dict(operation='MEMBER_OF', target_ids=['t0'], operands=[
        leaf('value', 't0', '"category":"boxing"', 'boxing', 'string'),
        leaf('member', 'h1', '"allowed":[]', 'boxing', 'string')])
    r = proof5.execute(pl, texts_of(p), ['t0'], policy_text=p['normative_sources'][0]['text'])
    assert r['status'] == 'VIOLATED', r


def test_mixed_address_duplicate_not_certified():
    row, p = packet('The total amount must not exceed 1000.', '', '\u2192 TOOL_CALL transfer: {"amount":600}')
    not_certified(P.proof_case(row, p, 'SUM_COMPARE_LE', [
        leaf('term', 't0', '"amount":600', 600), leaf('term', 't0', 'amount":600', 600),
        leaf('bound', 'h0', p['normative_sources'][0]['text'], 1000)]))


def test_array_sum_overlap_not_double_counted():
    row, p = packet('The total amount must not exceed 1000.',
        '\u2190 TOOL_RESPONSE past: {"transfers_today":[600]}', '\u2192 TOOL_CALL transfer: {"amount":100}')
    not_certified(P.proof_case(row, p, 'SUM_COMPARE_LE', [
        leaf('term', 'h1', '"transfers_today":[600]', 600), leaf('term', 'h1', 'transfers_today":[600]', 600),
        leaf('term', 't0', '"amount":100', 100), leaf('bound', 'h0', p['normative_sources'][0]['text'], 1000)]))


def test_array_sum_genuine_violation_still_certified():
    row, p = packet('The total amount must not exceed 1000.',
        '\u2190 TOOL_RESPONSE past: {"transfers_today":[600,300]}', '\u2192 TOOL_CALL transfer: {"amount":200}')
    case = P.proof_case(row, p, 'SUM_COMPARE_LE', [
        leaf('term', 'h1', '"transfers_today":[600,300]', 900),
        leaf('term', 't0', '"amount":200', 200), leaf('bound', 'h0', p['normative_sources'][0]['text'], 1000)])
    assert case['certificate'] is True


def test_ordinary_if_guard_blocks_certificate():
    row, p = packet('The amount must not exceed 1000 if the account is enterprise.', '',
        '\u2192 TOOL_CALL transfer: {"account_type":"consumer","amount":1300}')
    not_certified(P.proof_case(row, p, 'LE', [leaf('left', 't0', '"amount":1300', 1300),
        leaf('right', 'h0', p['normative_sources'][0]['text'], 1000)]))


def test_unconditional_bound_still_certified():
    row, p = packet('The amount must not exceed 1000.', '', '\u2192 TOOL_CALL transfer: {"amount":1300}')
    case = P.proof_case(row, p, 'LE', [leaf('left', 't0', '"amount":1300', 1300),
        leaf('right', 'h0', p['normative_sources'][0]['text'], 1000)])
    assert case['certificate'] is True


def test_numeric_entity_conflict():
    row, p = packet('A transfer may not exceed the daily limit of the same account.',
        '\u2190 TOOL_RESPONSE get_account: {"account_id":"A","limit":1000}\n'
        '\u2190 TOOL_RESPONSE get_account: {"account_id":"B","limit":400}',
        '\u2192 TOOL_CALL transfer: {"account_id":"A","amount":500}')
    not_certified(P.proof_case(row, p, 'LE', [leaf('left', 't0', '"amount":500', 500),
        leaf('right', 'h2', '"limit":400', 400)]))


def test_array_parent_identity_conflict():
    row, p = packet('Category must be in the allowed list for the same trainer.',
        '\u2190 TOOL_RESPONSE trainer: {"trainer_id":"T-1","allowed":["boxing"]}\n'
        '\u2190 TOOL_RESPONSE trainer: {"trainer_id":"T-2","allowed":["swim"]}',
        '\u2192 TOOL_CALL select: {"trainer_id":"T-1","category":"boxing"}')
    not_certified(P.proof_case(row, p, 'MEMBER_OF', [
        leaf('value', 't0', '"category":"boxing"', 'boxing', 'string'),
        leaf('member', 'h2', '"allowed":["swim"]', 'boxing', 'string')]))


def test_wrong_field_is_not_copy():
    row, p = packet('Report subtotal plus tax.',
        '\u2190 TOOL_RESPONSE invoice: {"invoice_id":"A","subtotal":10,"tax":10,"due_days":30}', 'Total is 30 EUR.')
    b = dict(operation='ARITHMETIC', expression='a+b', operands=[
        dict(name='a', source_id='h1', quote='"subtotal":10', value='10'),
        dict(name='b', source_id='h1', quote='"tax":10', value='10')])
    claim = dict(kind='number', value=30.0, span='30 EUR', context='Total is 30 EUR.')
    c = P.copied_case(row, p, b, claim)
    assert c['with_result_pairing']['status'] == 'MISMATCH'


def test_failed_result_echo_not_copy():
    row, p = packet('The date reported must be the next business day after the requested date.',
        '\u2192 TOOL_CALL get_slots: {"requested_date":"2025-04-11"}\n'
        '\u2190 TOOL_RESPONSE get_slots [ERROR]: {"ok":false,"requested_date":"2025-04-11","error":"No schedule available"}',
        'The next business day is 11 April 2025.')
    b = dict(operation='NEXT_BUSINESS_DAY', expression='', operands=[
        dict(name='date', source_id='h1', quote='"requested_date":"2025-04-11"', value='2025-04-11')])
    claim = dict(kind='date', value=dt.date(2025, 4, 11), span='11 April 2025',
                 context='The next business day is 11 April 2025.')
    c = P.copied_case(row, p, b, claim, df5.call_result_pairs(p['history']))
    assert c['with_result_pairing']['status'] == 'MISMATCH'


def test_duplicate_json_keys_not_certified():
    assert sourcejson.payload('{"limit":1000,"limit":100}') is None
    row, p = packet('Use the latest unambiguous tool-provided limit for the amount.',
        '\u2190 TOOL_RESPONSE limits: {"limit":1000,"limit":100}', '\u2192 TOOL_CALL transfer: {"amount":500}')
    not_certified(P.proof_case(row, p, 'LE', [leaf('left', 't0', '"amount":500', 500),
        leaf('right', 'h1', '"limit":100', 100)]))


def test_clause_scoped_rejection_still_asserts_new_claim():
    row, p = packet('Be accurate.', '', 'The previous quote was wrong; your new total is 2 + 2 = 5 EUR.')
    rec = df5.run(P.FakeClient([]), p, 'offline', flags=v5.FIXES)
    assert any(s['status'] != 'NOT_ASSERTED' for s in rec['self_checks']), rec['self_checks']


def test_pure_rejection_not_asserted():
    row, p = packet('Be accurate.', '', 'It is wrong that 2 + 2 = 5.')
    rec = df5.run(P.FakeClient([]), p, 'offline', flags=v5.FIXES)
    assert not rec['candidates']


def test_fuzzy_quantifier_reversal_unsupported():
    s = 'At least two successful checks are required before any change to an account.'
    a = 'At most two successful checks are required before any change to an account.'
    assert E.support(a, s)['status'] != 'SUPPORTED'


def test_fuzzy_action_substitution_unsupported():
    s = 'An account must not be deleted before identity verification is complete.'
    a = 'An account must not be modified before identity verification is complete.'
    assert E.support(a, s)['status'] != 'SUPPORTED'


def test_fuzzy_whitespace_and_case_still_supported():
    s = 'An account must not be deleted before identity verification is complete.'
    a = 'an account must not be deleted  before identity verification is complete'
    assert E.support(a, s)['status'] == 'SUPPORTED'


def _rec(status, cert=True):
    c = dict(certificate=cert, mode='PROOF', status='VIOLATED', target_id='t0', reason='r')
    return dict(base_error=False, pool=[dict(component='Ems', candidate=c, verification_status=status)])


def test_mech_only_on_unresolved():
    assert v5.decide(_rec('UNRESOLVED'), mech=True)[0] == 1
    for st in ('NOT_EXECUTED', 'UNCHECKED', 'UNCHECKED_QUEUE_BOUND'):
        assert v5.decide(_rec(st), mech=True)[0] == 0, st


def test_fuzzy_heading_merged_paraphrase_still_supported():
    """lb3L_003 rep2 (v2 replay regression): the verifier merged the section heading into the rule."""
    src = ("## Porting out\n- A port-out request (`port_out`) completes in 3 business days (Monday–Friday) counted from the "
           "next business day after the request. When telling the customer the completion date, compute it from today.\n")
    q = ("Porting out (`port_out`) completes in 3 business days (Monday–Friday) counted from the next business day after "
         "the request. When telling the customer the completion date, compute it from today.")
    assert E.support(q, src)['status'] == 'SUPPORTED'
    assert E.support(q, src, decisive=True)['status'] != 'SUPPORTED'


def test_cli_repair_is_opt_in(tmp_path):
    import pytest
    from guardian_truth.integrated import cli
    row, _ = packet('Be accurate.', '', 'Total is 4.')
    f = tmp_path / 'in.json'; f.write_text(json.dumps(dict(prompt=row['prompt'], response=row['response'])), encoding='utf-8')
    o = tmp_path / 'out.jsonl'
    assert cli.main([str(f), '--no-model', '--output', str(o)]) == 0
    r = json.loads(o.read_text(encoding='utf-8'))
    assert 'profile' not in r and 'binary' in r                       # default output unchanged
    with pytest.raises(SystemExit):
        cli.main([str(f), '--no-model', '--repair', 'r_fix'])
