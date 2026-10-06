"""Read-only repair review: seven old regressions and new parser-compatible contrasts.

Run: python -X utf8 docs/independent_repair_review_20261006/agent_code_probes.py --output NEW.json
No real model calls. Refuses existing report files. Imports tests and original runtime without editing them.
"""
from __future__ import annotations

import argparse
import datetime as dt
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import socket
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
sys.stdout.reconfigure(encoding='utf-8')


def no_network(*args, **kwargs):
    raise RuntimeError('AUDIT_NETWORK_FORBIDDEN')


socket.create_connection = no_network
socket.socket.connect = no_network
socket.socket.connect_ex = no_network
urllib.request.urlopen = no_network

from guardian_truth.parsing import parse_events
from guardian_truth.verification.pipeline import packet_for
from guardian_truth.verification.proof import texts_of
from guardian_truth.repair import df5, evidence as E, proof5, v5


def packet(policy, history, current):
    row = dict(prompt='\u27e6SYSTEM\u27e7\n' + policy + '\n'
               + '\u27e6ASSISTANT \u00b7 \u0445\u043e\u0434 1\u27e7\n' + history,
               response='\u27e6ASSISTANT \u00b7 \u0445\u043e\u0434 2\u27e7\n' + current)
    p = packet_for(row, 20000)
    assert p and p['coverage']['complete_input']
    return row, p


def leaf(role, sid, quote, value, typ='number'):
    return dict(role=role, source_id=sid, quote=quote, value=str(value), type=typ)


class FakeClient:
    def __init__(self, replies):
        self.replies = iter(replies)

    def call(self, *args, **kwargs):
        v = next(self.replies, None)
        return dict(content=json.dumps(v) if v is not None else None,
                    cached=True, transport={'status': 'NOT_EXECUTED_OFFLINE'} if v is None else {'status': 'FAKE'})


def proof_case(row, p, operation, operands):
    pl = dict(operation=operation, target_ids=['t0'], operands=operands)
    res = proof5.execute(pl, texts_of(p), ['t0'], policy_text=p['normative_sources'][0]['text'])
    req = dict(target_id='t0', policy_source_id='h0', policy_quote=p['normative_sources'][0]['text'],
               requirement=p['normative_sources'][0]['text'])
    check = dict(req_id='R1', mode='PROOF', **pl, evidence=[], reason='Offline hypothesis.', status='VIOLATED')
    rec = v5.ems_run(FakeClient([{'requirements': [req]}, {'checks': [check]}]), p, 'offline', 0, row, [], v5.FIXES)
    c = rec['candidates'][0] if rec['candidates'] else None
    arm = None
    if c:
        record = dict(base_error=False, pool=[dict(component='Ems', candidate=c, verification_status='UNRESOLVED')])
        arm = dict(ordinary=v5.decide(record)[0], mechanical=v5.decide(record, mech=True)[0])
    return dict(input=row, plan=pl, execution=res, certificate=proof5.certificate(res),
                ems_candidate=c, final_on_unresolved_verifier=arm)


def copied_case(row, p, binding, claim, pairs=None):
    texts = texts_of(p)
    rs = {h['source_id']: h['text'] for h in p['history'] if h['kind'] == 'result'}
    before = df5.evaluate(binding, claim, texts, None, {'t0'}, texts, rs, v5.FIXES, {})
    after = df5.evaluate(binding, claim, texts, None, {'t0'}, texts, rs, v5.FIXES, pairs)
    return dict(input=row, binding=binding, claim=claim, without_result_pairing=before,
                with_result_pairing=after, pairs=pairs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    if args.output.exists():
        ap.error('output exists; audit artifacts are immutable')
    names = ['test_add_zero_is_not_eager_division', 'test_datetime_keeps_seconds_and_timezone',
             'test_same_leaf_counted_twice_is_unresolved', 'test_exception_clause_blocks_mechanical_certificate',
             'test_latest_value_of_another_entity_is_entity_conflict', 'test_rejected_claim_is_not_an_assertion',
             'test_copy_suppression_is_scoped']
    spec = importlib.util.spec_from_file_location('repair_tests_for_audit', ROOT / 'tests/test_universal_repair.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    regressions = {}
    for n in names:
        getattr(module, n)()
        regressions[n] = 'PASS'
    cases = {}

    row, p = packet('The requested category must be in the allowed list.',
        '\u2190 TOOL_RESPONSE categories: {"allowed":[]}', '\u2192 TOOL_CALL select: {"category":"boxing"}')
    pl = dict(operation='MEMBER_OF', target_ids=['t0'], operands=[
        leaf('value', 't0', '"category":"boxing"', 'boxing', 'string'),
        leaf('member', 'h1', '"allowed":[]', 'boxing', 'string')])
    try:
        proof5.execute(pl, texts_of(p), ['t0'], policy_text=p['normative_sources'][0]['text'])
    except KeyError as ex:
        cases['empty_member_array_crash'] = dict(input=row, plan=pl, exception=type(ex).__name__, detail=str(ex),
            expected='Empty certified allowed set is valid input; boxing is not a member, without crashing.')
    assert 'empty_member_array_crash' in cases

    row, p = packet('The total amount must not exceed 1000.', '', '\u2192 TOOL_CALL transfer: {"amount":600}')
    cases['mixed_address_duplicate'] = proof_case(row, p, 'SUM_COMPARE_LE', [
        leaf('term', 't0', '"amount":600', 600), leaf('term', 't0', 'amount":600', 600),
        leaf('bound', 'h0', p['normative_sources'][0]['text'], 1000)])
    cases['mixed_address_duplicate']['expected'] = 'One transfer600 is one amount, not1200.'

    row, p = packet('The total amount must not exceed 1000.',
        '\u2190 TOOL_RESPONSE past: {"transfers_today":[600]}', '\u2192 TOOL_CALL transfer: {"amount":100}')
    cases['array_sum_overlap_A2'] = proof_case(row, p, 'SUM_COMPARE_LE', [
        leaf('term', 'h1', '"transfers_today":[600]', 600), leaf('term', 'h1', 'transfers_today":[600]', 600),
        leaf('term', 't0', '"amount":100', 100), leaf('bound', 'h0', p['normative_sources'][0]['text'], 1000)])
    cases['array_sum_overlap_A2']['expected'] = '600 prior plus100 current is700; the array is not a second event.'

    row, p = packet('The amount must not exceed 1000 if the account is enterprise.', '',
        '\u2192 TOOL_CALL transfer: {"account_type":"consumer","amount":1300}')
    cases['ordinary_if_guard_certified'] = proof_case(row, p, 'LE', [leaf('left', 't0', '"amount":1300', 1300),
        leaf('right', 'h0', p['normative_sources'][0]['text'], 1000)])
    cases['ordinary_if_guard_certified']['expected'] = 'The enterprise-only guard is false for the consumer account.'

    row, p = packet('A transfer may not exceed the daily limit of the same account.',
        '\u2190 TOOL_RESPONSE get_account: {"account_id":"A","limit":1000}\n'
        '\u2190 TOOL_RESPONSE get_account: {"account_id":"B","limit":400}',
        '\u2192 TOOL_CALL transfer: {"account_id":"A","amount":500}')
    cases['numeric_entity_not_checked'] = proof_case(row, p, 'LE', [leaf('left', 't0', '"amount":500', 500),
        leaf('right', 'h2', '"limit":400', 400)])
    cases['numeric_entity_not_checked']['expected'] = 'Same accountA limit1000 permits amount500; B is unrelated.'

    row, p = packet('Category must be in the allowed list for the same trainer.',
        '\u2190 TOOL_RESPONSE trainer: {"trainer_id":"T-1","allowed":["boxing"]}\n'
        '\u2190 TOOL_RESPONSE trainer: {"trainer_id":"T-2","allowed":["swim"]}',
        '\u2192 TOOL_CALL select: {"trainer_id":"T-1","category":"boxing"}')
    cases['array_parent_identity_lost'] = proof_case(row, p, 'MEMBER_OF', [
        leaf('value', 't0', '"category":"boxing"', 'boxing', 'string'),
        leaf('member', 'h2', '"allowed":["swim"]', 'boxing', 'string')])
    cases['array_parent_identity_lost']['expected'] = 'TrainerT-1 supports boxing; trainerT-2 set is irrelevant.'

    row, p = packet('Report subtotal plus tax.',
        '\u2190 TOOL_RESPONSE invoice: {"invoice_id":"A","subtotal":10,"tax":10,"due_days":30}', 'Total is 30 EUR.')
    b = dict(operation='ARITHMETIC', expression='a+b', operands=[
        dict(name='a', source_id='h1', quote='"subtotal":10', value='10'),
        dict(name='b', source_id='h1', quote='"tax":10', value='10')])
    claim = dict(kind='number', value=30.0, span='30 EUR', context='Total is 30 EUR.')
    cases['bound_result_wrong_field_copy'] = copied_case(row, p, b, claim)
    assert cases['bound_result_wrong_field_copy']['with_result_pairing']['status'] == 'SKIP'
    cases['bound_result_wrong_field_copy']['expected'] = '10+10=20; a due_days field does not establish total30.'

    row, p = packet('The date reported must be the next business day after the requested date.',
        '\u2192 TOOL_CALL get_slots: {"requested_date":"2025-04-11"}\n'
        '\u2190 TOOL_RESPONSE get_slots [ERROR]: {"ok":false,"requested_date":"2025-04-11","error":"No schedule available"}',
        'The next business day is 11 April 2025.')
    b = dict(operation='NEXT_BUSINESS_DAY', expression='', operands=[
        dict(name='date', source_id='h1', quote='"requested_date":"2025-04-11"', value='2025-04-11')])
    claim = dict(kind='date', value=dt.date(2025, 4, 11), span='11 April 2025', context='The next business day is 11 April 2025.')
    cases['failed_result_echo_suppression_A1'] = copied_case(row, p, b, claim, df5.call_result_pairs(p['history']))
    c = cases['failed_result_echo_suppression_A1']
    assert c['without_result_pairing']['status'] == 'MISMATCH' and c['with_result_pairing']['status'] == 'SKIP'
    c['expected'] = 'Friday11April next business day isMonday14April; failure echo is not success/state evidence.'

    row, p = packet('Use the latest unambiguous tool-provided limit for the amount.',
        '\u2190 TOOL_RESPONSE limits: {"limit":1000,"limit":100}', '\u2192 TOOL_CALL transfer: {"amount":500}')
    cases['duplicate_json_key_reaccepted'] = proof_case(row, p, 'LE', [leaf('left', 't0', '"amount":500', 500),
        leaf('right', 'h1', '"limit":100', 100)])
    events = parse_events(row['prompt'], 'prompt')
    cases['duplicate_json_key_reaccepted']['production_result_json_valid'] = [e.json_valid for e in events if e.kind == 'result']
    assert cases['duplicate_json_key_reaccepted']['production_result_json_valid'] == [False]
    cases['duplicate_json_key_reaccepted']['expected'] = 'Production rejects duplicate keys; proof cannot pick last limit as an unambiguous source.'

    row, p = packet('Be accurate.', '', 'The previous quote was wrong; your new total is 2 + 2 = 5 EUR.')
    rec = df5.run(FakeClient([]), p, 'offline', flags=v5.FIXES)
    cases['correction_assertion_false_not_asserted'] = dict(input=row, self_checks=rec['self_checks'], candidates=rec['candidates'],
        expected='Assistant rejects the old quote and asserts a new incorrect equality in the same sentence.')
    assert rec['self_checks'][0]['status'] == 'NOT_ASSERTED' and not rec['candidates']

    for key, source, altered in [('quantifier_reversal_fuzzy',
         'At least two successful checks are required before any change to an account.',
         'At most two successful checks are required before any change to an account.'),
        ('regulated_action_substitution_fuzzy', 'An account must not be deleted before identity verification is complete.',
         'An account must not be modified before identity verification is complete.')]:
        cases[key] = dict(source=source, altered=altered, support=E.support(altered, source),
                          expected='Changed semantic relation must not be certified as the original quote.')
        assert cases[key]['support']['status'] == 'SUPPORTED'

    certcases = ['mixed_address_duplicate', 'array_sum_overlap_A2', 'ordinary_if_guard_certified',
                 'numeric_entity_not_checked', 'array_parent_identity_lost', 'duplicate_json_key_reaccepted']
    for name in certcases:
        assert cases[name]['certificate'] is True and cases[name]['ems_candidate']['certificate'] is True
        assert cases[name]['final_on_unresolved_verifier'] == dict(ordinary=0, mechanical=1)
    files = sorted((ROOT / 'src/guardian_truth/repair').glob('*.py'))
    report = dict(scope='Admission-safety/parser counterexamples and matched regression unit checks; no live-model quality claim.',
        model_http_calls=0, network_blocked=True, old_regressions=regressions, new_cases=cases,
        source_sha256={str(f.relative_to(ROOT)): hashlib.sha256(f.read_bytes()).hexdigest() for f in files})
    def encode(x):
        if isinstance(x, (dt.date, dt.datetime)):
            return x.isoformat()
        if isinstance(x, Decimal):
            return str(x)
        raise TypeError(type(x).__name__)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8', newline='\n') as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=encode)
        f.write('\n')
    print(f'PASS: {len(regressions)} old regressions and {len(cases)} asserted new contrasts; no network')


if __name__ == '__main__':
    main()
