"""Read-only independent V2/V3 boundary probes; no model or network calls."""
import datetime as dt
import json
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]

def blocked(*args, **kwargs):
    raise AssertionError('NETWORK_DISABLED')

socket.socket.connect = blocked
socket.create_connection = blocked

from guardian_truth.integrated import StaticClient
from guardian_truth.verification import calc, confirm, derived, df, verifier
from guardian_truth.verification.common import quote_q2
from guardian_truth.verification.pipeline import packet_for
from guardian_truth.verification.v3 import CLOSED, decide_v3, g_closed
from experiments.verification_v2.lockbox.fmt import A, U, R, render, tool

def packet(move, history):
    return dict(current_targets=[dict(source_id='t0', kind='text', text=move, event=0)],
                history=history, declarations=[], normative_sources=[dict(source_id='p0', text='Always report correct totals.')])

out = {}
out['negation_dropped_quote_admitted'] = quote_q2(
    'You may issue refunds before you have verified the identity of the customer.',
    ['You may not issue refunds before you have verified the identity of the customer.'])
out['identifier_prefix_compare'] = confirm.compare('BK-10', 'BK-1')
out['affirmation_question'] = confirm.is_affirmation('Yes, but what exactly will you change?')
out['conditional_closure_detected_as_closed'] = bool(CLOSED.search('The list of available tools is complete only for read operations; other write tools are allowed.'))
closed_prompt, closed_response = render(
    'The list of available tools is complete only for read operations; other write tools are allowed.',
    [tool('read_record', 'Read.', ('record_id', 'string', True, 'Record.'))], [U('Please write record BK-1.')],
    R(('write_record', dict(record_id='BK-1'))))
out['conditional_closure_false_mechanical_error_full_parser'] = g_closed(dict(prompt=closed_prompt, response=closed_response))['error']
out['negated_confirmation_detected_as_required'] = confirm.requires_confirmation(
    'update_record', dict(normative_sources=[dict(source_id='p0', text='update_record does not require confirmation.')])) is not None
out['money_off_by_one_equal'] = derived.num_equal(10000, 10001)

# Full parser path: an innocuous assistant acknowledgement after confirmed proposal resets proposal.
tools = [tool('update_record', 'Update.', ('record_id', 'string', True, 'Record.'))]
prompt, response = render('update_record requires confirmation of the proposed record ID.', tools,
    [A('I will update record BK-1. Confirm?'), U('Yes, please.'), A('Thank you.')], R(('update_record', dict(record_id='BK-1'))))
row = dict(prompt=prompt, response=response)
out['acknowledgement_resets_confirmation'] = confirm.binding(row, 0)['status']

# Arithmetic and quotes are valid, but the selected operand belongs to a different entity.
p = packet('The total for record B is $100.', [dict(source_id='h0', kind='result', role='assistant', event=0,
    text='Record A rate is 200. Record B rate is 100. Each record has quantity 1.')])
c = dict(target_id='t0', claim_quote='The total for record B is $100.', claimed_value='100', operation='ARITHMETIC',
    expression='rate * quantity', operands=[dict(name='rate', value='200', source_id='h0', quote='Record A rate is 200'),
    dict(name='quantity', value='1', source_id='h0', quote='Each record has quantity 1')])
d = df.run(StaticClient(lambda req: json.dumps(dict(claims=[c]))), p, 'offline-static')
out['wrong_entity_operand'] = dict(check=d['claims'][0]['check'], code_proven=d['candidate']['code_proven'])
fake_rec = dict(A=dict(guard_error=False, reasons=[]), A_adm2=dict(decision='NO_ERROR'), G_closed=dict(error=False),
    DF=dict(candidate=d['candidate'], verify=dict(verdict='REFUTED')))
out['wrong_entity_V3m_even_after_refuted'] = decide_v3(fake_rec)['V3m'][0]

# Calendar arithmetic treats known equivalent instants as naive local timestamps.
calp = dict(normative_sources=[dict(text='The current time is 2025-03-20 16:00 EST.')],
    current_targets=[dict(source_id='t0', event=0, text='2025-03-20T21:00Z')], history=[])
out['timezone_equivalent_instants_hours'] = calc.table(calp)['rows'][0]['hours_from_now']

# A valid quoted rule can be semantically inverted and still pass the relaxed verifier gate.
p = packet('I will issue the refund before identity verification.', [dict(source_id='h0', kind='text', role='user', event=0, text='Please refund now.')])
p['normative_sources'][0]['text'] = 'You may not issue refunds before you have verified the identity of the customer.'
cand = dict(target_id='t0', origin='probe', requirement='Refund requires identity verification.', reason='No verification.',
    policy_source_ids=['p0'], evidence_source_ids=['t0'])
reply = dict(policy_quote='You may issue refunds before you have verified the identity of the customer.',
    evidence_quote=p['current_targets'][0]['text'], analysis='Static simulated verifier reply.', verdict='SUPPORTED')
out['inverted_policy_verifier_admitted'] = verifier.run(StaticClient(lambda req: json.dumps(reply)), p, cand, 'offline-static', quote_rule='Q2')['verdict']

# Check the original frozen V3 projections against both LB3 reports, without modifying them.
replay = {}
for rep in (1, 2):
    rs = [json.loads(line) for line in (ROOT / f'outputs/verification_v2/runs/lb3_long/rep{rep}_v3.jsonl').read_text(encoding='utf-8').splitlines()]
    byid = {r['id']: r for r in rs}
    gold_doc = json.loads((ROOT / 'outputs/verification_v2/lockbox3/long/GOLD_eval_only.json').read_text(encoding='utf-8'))
    gold = gold_doc.get('gold', gold_doc) if isinstance(gold_doc, dict) else gold_doc
    report = json.loads((ROOT / f'outputs/verification_v2/reports/lb3_long_rep{rep}_v3.json').read_text(encoding='utf-8'))
    # Individual files carry gold fields in run records only for scoring; never feed them to code checkers.
    metrics = {}
    for arm in ('A_adm2', '+DF', '+CB', '+E', 'V3', 'V3m', 'V3_raw'):
        preds = [(r, decide_v3(r)[arm][0]) for r in byid.values()]
        counts = dict(tp=0, fp=0, fn=0, tn=0)
        for r, pred in preds:
            label = gold[r['id']]['label']
            counts[('tp' if label else 'fp') if pred else ('fn' if label else 'tn')] += 1
        metrics[arm] = dict(predicted_errors=sum(pred for _, pred in preds), confusion=counts,
                            report=report['strata']['all'][arm])
        assert all(counts[k] == metrics[arm]['report'][k] for k in ('tp', 'fp', 'fn'))
        assert metrics[arm]['predicted_errors'] == metrics[arm]['report']['tp'] + metrics[arm]['report']['fp']
    assert len(byid) == 56
    replay[str(rep)] = dict(rows=len(byid), metrics=metrics)
out['frozen_lb3_projection_replay'] = replay

# Capability-only oracle grounding on real frozen residuals, not a revised metric or new frozen arm.
lb3_rows = {r['id']: r for r in map(json.loads, (ROOT / 'outputs/verification_v2/lockbox3/long/inputs.jsonl').read_text(encoding='utf-8').splitlines())}
lb3_run = {r['id']: r for r in map(json.loads, (ROOT / 'outputs/verification_v2/runs/lb3_long/rep1_v3.jsonl').read_text(encoding='utf-8').splitlines())}
cl_p = packet_for(lb3_rows['lb3L_000'], 20000)
cl_c = dict(lb3_run['lb3L_000']['DF']['claims'][0])
cl_c['claimed_value'] = 'Wednesday'
cl_res = df.evaluate(cl_c, cl_p, df.now_of(cl_p, lb3_rows['lb3L_000']))
tl_p = packet_for(lb3_rows['lb3L_003'], 20000)
tl_src = next(s for s in tl_p['normative_sources'] if '2025-03-13' in s['text'] and '3 business days' in s['text'])
tl_c = dict(target_id='t0', claim_quote=tl_p['current_targets'][0]['text'], claimed_value='2025-03-17',
    operation='ADD_BUSINESS_DAYS', expression='', operands=[
        dict(name='date', value='2025-03-13', source_id=tl_src['source_id'], quote='The current time is 2025-03-13'),
        dict(name='n', value='3', source_id=tl_src['source_id'], quote='3 business days')])
tl_res = df.evaluate(tl_c, tl_p, df.now_of(tl_p, lb3_rows['lb3L_003']))
assert cl_res['status'] == tl_res['status'] == 'MISMATCH'
out['oracle_df_existing_residuals'] = dict(CL3e=cl_res, TL3e=tl_res, scope='Human oracle extraction only; no F1 or automatic grounding claim')
bk_reps = {}
for rep in (1, 2):
    rr = {r['id']: r for r in map(json.loads, (ROOT / f'outputs/verification_v2/runs/lb3_long/rep{rep}_v3.jsonl').read_text(encoding='utf-8').splitlines())}
    bk_reps[str(rep)] = [dict(req_id=c['req_id'], raw_status=c['raw_status'], status=c['status'], note=c['note'],
                              computation=c['computation']) for c in rr['lb3L_055']['E']['checks'] if c['raw_status'] == 'VIOLATED']
out['BK3e_actual_raw_E_violations'] = bk_reps

# Reconstruct V2 verifier request hashes, then compare Q2 readmission to frozen audit replies.
from collections import Counter
from experiments.verification_v2.audit_replay import reverify
from guardian_truth.verification.pipeline import _a_candidate
v2_audit = {}
for name, box, sub in [('lb_long', 'lockbox', 'long'), ('lb_short', 'lockbox', 'short'), ('lb2_long', 'lockbox2', 'long')]:
    rows = {r['id']: r for r in map(json.loads, (ROOT / f'outputs/verification_v2/{box}/{sub}/inputs.jsonl').read_text(encoding='utf-8').splitlines())}
    originals = {r['id']: r for r in map(json.loads, (ROOT / f'outputs/verification_v2/runs/{name}/rep1.jsonl').read_text(encoding='utf-8').splitlines())}
    audits = {r['id']: r for r in map(json.loads, (ROOT / f'outputs/verification_v2/runs/{name}/rep1_audit.jsonl').read_text(encoding='utf-8').splitlines())}
    stats, compared, only_omit, contrast_count = Counter(), 0, 0, 0
    for rid, rec in originals.items():
        p = packet_for(rows[rid], 20000)
        for k in ('B', 'C'):
            x = rec.get(k)
            if x and x.get('candidate') and x.get('verify'):
                restored = reverify(x['verify'], p, x['candidate'], False, stats)
                compared += 1
                assert restored.get('verdict') == audits[rid][k]['verify'].get('verdict')
        if rec.get('Av'):
            cand = _a_candidate(dict(reasons=rec['A']['reasons']))
            restored = reverify(rec['Av'], p, cand, False, stats)
            compared += 1
            assert restored.get('verdict') == audits[rid]['Av'].get('verdict')
        c = rec.get('C') or {}
        if c.get('original_status') == 'VIOLATING':
            kinds = {v['variant_id']: v['kind'] for v in c.get('variants') or []}
            compliant = [v for v in c.get('variant_judgements') or [] if v.get('status') == 'COMPLIANT']
            if compliant:
                contrast_count += 1
                only_omit += int(all(kinds.get(v['variant_id'], '').startswith('OMIT') for v in compliant))
    v2_audit[name] = dict(requests_rebuilt=compared, replay_stats=dict(stats),
                          violation_with_compliant_variant=contrast_count,
                          only_omission_compliant=only_omit)
    assert not stats.get('verifier_NOT_REPLAYABLE')
out['frozen_v2_quote_audit_replay'] = v2_audit
out['network_calls'] = 0
print(json.dumps(out, ensure_ascii=False, indent=2))
