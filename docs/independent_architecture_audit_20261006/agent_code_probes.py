"""Seven source/parser-compatible admission counterexamples; no real model calls.

Run: python -X utf8 docs/independent_architecture_audit_20261006/agent_code_probes.py --output NEW.json
Writes only a new report, refuses existing paths. All runtime source is read-only.
"""
from __future__ import annotations

import argparse
import hashlib
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

from guardian_truth.verification import df4, ems, proof
from guardian_truth.verification.pipeline import packet_for
from guardian_truth.verification.v4 import decide_v4


class FakeClient:
    def __init__(self, payloads):
        self.payloads = iter(payloads)
        self.calls = 0

    def call(self, *args, **kwargs):
        self.calls += 1
        return {'content': json.dumps(next(self.payloads)), 'cached': True}


def packet(policy, history, current):
    row = dict(prompt='\u27e6SYSTEM\u27e7\n' + policy + '\n'
               + '\u27e6ASSISTANT \u00b7 \u0445\u043e\u0434 1\u27e7\n' + history,
               response='\u27e6ASSISTANT \u00b7 \u0445\u043e\u0434 2\u27e7\n' + current)
    p = packet_for(row, 20000)
    assert p and p['coverage']['complete_input'] and len(p['current_targets']) == 1
    return row, p


def leaf(role, sid, quote, value, typ='number'):
    return dict(role=role, source_id=sid, quote=quote, value=str(value), type=typ)


def plan(operation, operands):
    return dict(operation=operation, target_ids=['t0'], operands=operands)


def execute(p, pl):
    return proof.execute(pl, proof.texts_of(p), ['t0'])


def ems_probe(p, pl):
    req = dict(target_id='t0', policy_source_id='h0', policy_quote=p['normative_sources'][0]['text'],
               requirement=p['normative_sources'][0]['text'])
    check = dict(req_id='R1', mode='PROOF', **pl, evidence=[], reason='Offline admission hypothesis.', status='VIOLATED')
    c = FakeClient([{'requirements': [req]}, {'checks': [check]}])
    rec = ems.run(c, p, 'offline-probe')
    assert c.calls == 2
    assert rec['candidate']['code_proven'] is True
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    if args.output.exists():
        ap.error('output exists; cannot overwrite an audit artifact')
    cases = {}

    row, p = packet('Use the latest observed address of the same order.',
                    '\u2190 TOOL_RESPONSE get_order: {"order_id":"A", "address":"Alpha"}\n'
                    '\u2190 TOOL_RESPONSE get_order: {"order_id":"B", "address":"Beta"}',
                    '\u2192 TOOL_CALL ship: {"order_id":"A", "address":"Alpha"}')
    pl = plan('LATEST_VALUE_EQ', [leaf('value', 't0', '"address":"Alpha"', 'Alpha', 'string'),
              leaf('observed', 'h1', '"address":"Alpha"', 'Alpha', 'string'),
              leaf('observed', 'h2', '"address":"Beta"', 'Beta', 'string')])
    rec = ems_probe(p, pl)
    rec['verify'] = {'verdict': 'REFUTED'}
    arms = {k: v[0] for k, v in decide_v4(dict(A=dict(guard_error=False, reasons=[]),
             A_adm2=dict(decision='NO_ERROR'), Ems=rec)).items()}
    assert arms['A_Ems'] == 0 and arms['V4_mechanical'] == 1
    cases['wrong_entity_latest'] = dict(input=row, plan=pl, execution=execute(p, pl),
                                      candidate=rec['candidate'], verifier='REFUTED', arm_binary=arms,
                                      expected_relation='Same order A address is Alpha; unrelated B must be excluded.')

    row, p = packet('Except when supervisor_override is true, the amount must not exceed 1000.', '',
                    '\u2192 TOOL_CALL transfer: {"amount":1300,"supervisor_override":true}')
    pl = plan('LE', [leaf('left', 't0', '"amount":1300', 1300),
                    leaf('right', 'h0', p['normative_sources'][0]['text'], 1000)])
    rec = ems_probe(p, pl)
    cases['exception_not_bound'] = dict(input=row, plan=pl, execution=execute(p, pl), candidate=rec['candidate'],
                                      expected_relation='The exact policy exception applies.')

    row, p = packet('The total amount must not exceed 1000.', '', '\u2192 TOOL_CALL transfer: {"amount":600}')
    pl = plan('SUM_COMPARE_LE', [leaf('term', 't0', '"amount":600', 600),
              leaf('term', 't0', p['current_targets'][0]['text'], 600),
              leaf('bound', 'h0', p['normative_sources'][0]['text'], 1000)])
    r = execute(p, pl)
    assert r['status'] == 'VIOLATED'
    cases['same_fact_counted_twice'] = dict(input=row, plan=pl, execution=r, expected_relation='One amount600 total is600.')

    row, p = packet('Report subtotal plus tax.',
                    '\u2190 TOOL_RESPONSE invoice: {"invoice_id":"A","subtotal":10,"tax":10}\n'
                    '\u2190 TOOL_RESPONSE profile: {"customer_id":"B","age":30}', 'Total is 30 EUR.')
    b = dict(operation='ARITHMETIC', expression='a+b', operands=[
        dict(name='a', source_id='h1', quote='"subtotal":10', value='10'),
        dict(name='b', source_id='h1', quote='"tax":10', value='10')])
    claim = dict(kind='number', value=30.0, span='30 EUR')
    texts = proof.texts_of(p)
    before = df4.evaluate_binding(b, claim, texts, None, {'t0'}, texts, [])
    after = df4.evaluate_binding(b, claim, texts, None, {'t0'}, texts,
                                 [s['text'] for s in p['history'] if s['kind'] == 'result'])
    assert before['status'] == 'MISMATCH' and after['status'] == 'SKIP'
    cases['unrelated_value_suppresses_derivation'] = dict(input=row, binding=b, claim=claim,
        without_copy_filter=before, with_original_result_filter=after,
        expected_relation='10+10=20; unrelated age30 does not justify total30.')

    row, p = packet('Be accurate.', '', 'I reject the incorrect claim 2 + 2 = 5 EUR.')
    c = FakeClient([])
    rec = df4.run(c, p, 'offline-probe')
    assert c.calls == 0 and rec['candidate']['relation_by_code'] is True
    cases['negated_expression_ownership'] = dict(input=row, candidate=rec['candidate'], self_checks=rec['self_checks'],
                                               expected_relation='Assistant rejects, rather than asserts, the false equality.')

    row, p = packet('Execute before the deadline 2025-01-01T10:00:30.', '',
                    '\u2192 TOOL_CALL execute: {"when":"2025-01-01T10:00:10"}')
    pl = plan('BEFORE', [leaf('left', 't0', p['current_targets'][0]['text'], '2025-01-01T10:00:10', 'datetime'),
                        leaf('right', 'h0', p['normative_sources'][0]['text'], '2025-01-01T10:00:30', 'datetime')])
    r = execute(p, pl)
    assert r['status'] == 'VIOLATED'
    cases['datetime_precision_loss'] = dict(input=row, plan=pl, execution=r,
        expected_relation='10:00:10 is before10:00:30 on the same day and time basis.')

    row, p = packet('Use numbers 7 and 0.', '', '7 + 0 = 7 EUR.')
    # The executor values do not require the prose arithmetic extractor.
    pl = plan('ADD', [leaf('left', 'h0', p['normative_sources'][0]['text'], 7),
                     leaf('right', 'h0', p['normative_sources'][0]['text'], 0),
                     leaf('result', 't0', p['current_targets'][0]['text'], 7)])
    r = execute(p, pl)
    assert r.get('note') == 'EXEC_ERROR:ZeroDivisionError'
    cases['add_zero_eager_division'] = dict(input=row, plan=pl, execution=r, expected_relation='7+0=7; division is not requested.')

    assert len(cases) == 7
    modules = ('proof.py', 'df4.py', 'ems.py', 'v4.py')
    report = dict(scope='Deterministic fake model plans on production parser packets; not live-model quality or frequency.',
        model_http_calls=0, network_blocked=True, cases=cases,
        runtime_source_sha256={m: hashlib.sha256((ROOT / 'src/guardian_truth/verification' / m).read_bytes()).hexdigest()
                              for m in modules})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8', newline='\n') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print('PASS: seven asserted offline counterexamples; zero model HTTP calls')


if __name__ == '__main__':
    main()
