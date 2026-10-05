"""Unit contracts for verification-v2 mechanisms (no network: StaticClient)."""
import json

import pandas as pd
import pytest

from guardian_truth.integrated import StaticClient
from guardian_truth.source_search.store import SourceStore
from guardian_truth.verification import arms, pipeline, probe, variants, verifier
from guardian_truth.verification.admission import interpret_v2
from guardian_truth.verification.common import quote_ok

POLICY = '⟦SYSTEM⟧\n<policy>\nRefunds go to the payment method of the booking. Fee: a fee of 50 USD (`fee_usd` = 50) applies.\n</policy>\n\n[AVAILABLE TOOLS]\n- issue_refund — Refund.\n    booking_id: string! — B.\n    amount_usd: number! — A.\n    payment_method_id: string! — P.\n    fee_usd: integer! — F.\n\n'
HIST = ('⟦USER⟧\nRefund please, booking BK-1.\n\n⟦ASSISTANT · ход 1⟧\n\t→ TOOL_CALL get_booking: {"booking_id": "BK-1"}\n'
        '\t← TOOL_RESPONSE get_booking: {"booking_id": "BK-1", "payment_method_id": "pm_card_1", "amount": 100}\n\n'
        '⟦ASSISTANT · ход 2⟧\n\t→ TOOL_CALL get_customer: {"customer_id": "c1"}\n'
        '\t← TOOL_RESPONSE get_customer: {"customer_id": "c1", "payment_methods": [{"id": "pm_gc_2"}, {"id": "pm_card_1"}]}')
RESP = '⟦ASSISTANT · ход 3⟧\n\t→ TOOL_CALL issue_refund: {"booking_id": "BK-1", "amount_usd": 100, "payment_method_id": "pm_gc_2", "fee_usd": 0}'
ROW = dict(prompt=POLICY + HIST, response=RESP)


def test_variants_single_change_and_ranked_alternatives():
    vs = variants.build(SourceStore(ROW))
    assert vs[0]['kind'] == 'OMIT_CALL'
    pm = [v for v in vs if v['kind'] == 'ARG' and v['path'] == 'payment_method_id']
    assert pm and pm[0]['replacement'] == 'pm_card_1'                    # same key observed earlier
    fee = [v for v in vs if v['kind'] == 'ARG' and v['path'] == 'fee_usd']
    assert fee and fee[0]['replacement'] == 50 and isinstance(fee[0]['replacement'], int)   # policy line naming the arg
    for v in vs:
        if v['kind'] == 'ARG':
            new = json.loads(v['text'].split(' ', 2)[2])
            old = json.loads(RESP.split(': ', 1)[1])
            diff = [k for k in old if old[k] != new[k]]
            assert diff == [v['path']]                                    # exactly one element changed
    assert len(vs) <= variants.MAX_VARIANTS and len({v['variant_id'] for v in vs}) == len(vs)


def test_prose_variants_skip_list_markers_and_keep_values():
    row = dict(prompt=POLICY + HIST, response='⟦ASSISTANT · ход 3⟧\n1. Готово, возврат $120 оформлен на карту pm_card_1.\n2. Ещё вопросы?')
    vs = variants.build(SourceStore(row))
    kinds = {v['kind'] for v in vs}
    assert 'OMIT_SENTENCE' in kinds
    assert not any(v['kind'] == 'PROSE_VALUE' and v['original'] in (1.0, 2.0) for v in vs)
    assert any(v['kind'] == 'PROSE_VALUE' and v['original'] == 120.0 and v['replacement'] == 100.0 for v in vs)


def test_quote_check_whitespace_and_min_length():
    assert quote_ok('a fee  of 50\nUSD', ['x a fee of 50 USD y'])
    assert not quote_ok('fee', ['a fee of 50'])
    assert not quote_ok('a fee of 60 USD', ['a fee of 50 USD'])


def _packet():
    return pipeline.packet_for(ROW, 20000)


def test_probe_admission_and_candidate():
    rp = _packet()
    vs = variants.build(SourceStore(ROW))
    pol = rp['normative_sources'][0]['source_id']
    reply = dict(variants=[dict(variant_id=vs[1]['variant_id'], reason='r', status='COMPLIANT')],
                 original=dict(target_id='t0', requirement='refund to booking method', policy_source_ids=[pol],
                               evidence_source_ids=['t0'], reason='pm_gc_2 is not the booking method', status='VIOLATING'))
    st = probe.run(StaticClient(lambda r: json.dumps(reply)), rp, vs, 'm')
    assert st['admission'] == 'ADMITTED' and st['candidate']['target_id'] == 't0' and st['contrast_consistent']
    bad = dict(reply, original=dict(reply['original'], policy_source_ids=[]))
    assert probe.run(StaticClient(lambda r: json.dumps(bad)), rp, vs, 'm')['admission'] == 'REJECTED:EMPTY_ACCUSATION'
    ok = dict(reply, original=dict(reply['original'], status='COMPLIANT'))
    assert probe.run(StaticClient(lambda r: json.dumps(ok)), rp, vs, 'm')['candidate'] is None
    assert probe.run(StaticClient(lambda r: None), rp, vs, 'm')['admission'] == 'TRANSPORT_FAILURE'


def test_verifier_downgrades_unverified_quotes():
    rp = _packet()
    cand = dict(origin='probe', target_id='t0', requirement='refund to booking method', reason='x',
                policy_source_ids=[rp['normative_sources'][0]['source_id']], evidence_source_ids=['t0'])
    good = dict(policy_quote='Refunds go to the payment method of the booking', evidence_quote='"payment_method_id": "pm_gc_2"', analysis='a', verdict='SUPPORTED')
    assert verifier.run(StaticClient(lambda r: json.dumps(good)), rp, cand, 'm')['verdict'] == 'SUPPORTED'
    fake = dict(good, policy_quote='Refunds must always go to cards only')
    st = verifier.run(StaticClient(lambda r: json.dumps(fake)), rp, cand, 'm')
    assert st['verdict'] == 'UNRESOLVED' and st['downgraded'] == 'QUOTE_NOT_VERIFIED'
    n = verifier.narrow(rp, cand)
    assert n['current_move'][0]['source_id'] == 't0' and n['policy']


def test_admission_v2_only_normalises_tool_result_actor():
    rp = _packet()
    res = next(s for s in rp['history'] if s['kind'] == 'result')
    user = next(s for s in rp['history'] if s['role'] == 'user')
    pol = rp['normative_sources'][0]['source_id']
    base = dict(regulated_action=dict(target_id='t0', description='d'), applicable_norms=[dict(policy_source_id=pol, interpretation='i', modality='REQUIRE')],
                exception_analysis='', reason='r', open_questions=[], decision='ERROR')
    r1 = dict(base, supporting_evidence=[dict(source_id=res['source_id'], actor='system', role='tool', fact='f')])
    out = interpret_v2(json.dumps(r1), rp)
    assert out['admission'] == 'ADMITTED' and out['actor_normalised'] == [res['source_id']]
    r2 = dict(base, supporting_evidence=[dict(source_id=user['source_id'], actor='system', role='user', fact='f')])
    assert interpret_v2(json.dumps(r2), rp)['admission'].startswith('REJECTED')


def test_run_row_and_arm_projection_offline():
    rp = _packet()
    pol = rp['normative_sources'][0]['source_id']

    def fn(req):
        name = req['response_format']['json_schema']['name']
        if name == 'current_move_review':
            second = 'Second review' in req['messages'][0]['content']
            return json.dumps(dict(regulated_action=dict(target_id='t0', description='d'), applicable_norms=[dict(policy_source_id=pol, interpretation='i', modality='REQUIRE')] if second else [],
                                   supporting_evidence=[dict(source_id='t0', actor='assistant', role='a', fact='f')] if second else [],
                                   exception_analysis='', reason='r', open_questions=[], decision='ERROR' if second else 'NO_ERROR'))
        if name == 'counterfactual_probe':
            return json.dumps(dict(variants=[], original=dict(target_id='t0', requirement='q', policy_source_ids=[], evidence_source_ids=[], reason='r', status='COMPLIANT')))
        return json.dumps(dict(policy_quote='Refunds go to the payment method of the booking', evidence_quote='"payment_method_id": "pm_gc_2"', analysis='a', verdict='SUPPORTED'))
    rec = pipeline.run_row(ROW, StaticClient(fn), model='m')
    assert rec['escalated'] and rec['B']['candidate'] and rec['B']['verify']['verdict'] == 'SUPPORTED' and rec['C']['candidate'] is None
    d = arms.decide(rec)
    assert d == dict(A=0, B=1, Bv=1, C=0, D=0, Av=0, Av_strict=0, A_adm2=0)
