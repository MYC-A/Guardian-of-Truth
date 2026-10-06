"""Verification V4 (docs/verification_v4/PROTOCOL.md): guard_adm2 control + DF4 (code-first derived facts),
Ems (fixed E with typed multi-source proof executor), AT (one all-target call) and its matched control CTRL
(ordinary second reviewer on the same T_multi rows); CB as shadow. A decides first; an A ERROR is final. Every
mechanism runs on its deterministic trigger and its candidate is checked by the V3 Q2 narrow verifier. Arms are
projections of the single record (decide_v4)."""
from __future__ import annotations

from ..integrated import ReviewConfig, review
from ..integrated.transport import sha
from . import alltarget, confirm, df, df4, ems, second
from .admission import interpret_v2
from .pipeline import packet_for
from . import verifier


def _verify(client, rp, cand, model, attempt, tag, **kw):
    """V3 Q2 verifier (squash_ws, one invalid-JSON retry) + V4 multi-piece evidence admission (PROTOCOL §4, spec §9)."""
    v = verifier.run(client, rp, cand, model, attempt, tag=tag, quote_rule='Q2', squash_ws=True, multi_piece=True, **kw)
    if v.get('admission') == 'INVALID_JSON':
        v2 = verifier.run(client, rp, cand, model, attempt + 100, tag=tag, quote_rule='Q2', squash_ws=True, multi_piece=True, **kw)
        v2['first_invalid'] = {k: v.get(k) for k in ('key', 'finish_reason', 'admission')}
        v = v2
    return v

VERSION = 'guardian-v4'
COMPONENTS = ('DF4', 'Ems', 'AT', 'CTRL', 'CB')


def run_v4(row, client, *, provider='mistral', model='ministral-14b-2512', budget=20000, attempt=0, components=COMPONENTS):
    cfg = ReviewConfig.profile('guard', provider=provider, model=model, budget_bytes=budget, attempt=attempt, admission='v1')   # cached A request
    a = review(row['prompt'], row['response'], cfg, client=client)
    out = dict(version=VERSION, A=dict(final=a['final_decision'], binary=a['binary'], proof=a['proof_status'], owner=a['decision_owner'],
                                     guard_error=a['guard']['established_error'], reasons=a['reasons'], steps=a['steps'], cost=a['cost']))
    rp = packet_for(row, budget)
    if rp is None:
        out['skipped'] = 'NO_PACKET'
        return out
    assert sha(rp) == a['packet']['packet_sha256'], 'packet drift between A and V4'
    out['n_targets'] = len(rp['current_targets'])
    s0 = next((s for s in a['steps'] if s.get('tag') == 'review'), None)
    adm = dict(decision=None, admission='NO_REVIEW_STEP')
    if s0 is not None and s0.get('raw_content') is not None:
        v2 = interpret_v2(s0['raw_content'], rp)
        adm = dict(admission=v2['admission'], decision=v2['decision'], actor_normalised=v2['actor_normalised'])
        if v2['admitted']:
            adm.update(target_id=v2['admitted']['regulated_action']['target_id'], reason=v2['admitted']['reason'],
                       norms=[n['policy_source_id'] for n in v2['admitted']['applicable_norms']],
                       evidence=[e['source_id'] for e in v2['admitted']['supporting_evidence']])
    out['A_adm2'] = adm
    base = adm.get('decision') == 'ERROR' or bool(a['guard']['established_error'])
    out['base_error'] = base
    if base or not rp['current_targets'] or not rp['normative_sources']:
        out['triggers'] = None
        return out
    et = ems.trigger(rp, row)
    trig = dict(T_multi=len(rp['current_targets']) >= 2, T_calc=df.trigger(rp, row), T_quant=et['quant'],
                T_confirm=confirm.trigger(rp, row), fallback=[f['source_id'] for f in et['fallback']])
    out['triggers'] = trig
    if 'DF4' in components and trig['T_calc']:
        d = df4.run(client, rp, model, attempt, row=row)
        if d.get('candidate'):
            d['verify'] = _verify(client, rp, d['candidate'], model, attempt, 'verify_DF4')
        out['DF4'] = d
    if 'Ems' in components and (trig['T_multi'] or trig['T_quant']):
        e = ems.run(client, rp, model, attempt, row=row, fallback=et['fallback'])
        if e.get('candidate'):
            e['verify'] = _verify(client, rp, e['candidate'], model, attempt, 'verify_Ems')
        out['Ems'] = e
    if 'AT' in components and trig['T_multi']:
        t = alltarget.run(client, rp, model, attempt)
        if t.get('candidate'):
            t['verify'] = _verify(client, rp, t['candidate'], model, attempt, 'verify_AT')
        out['AT'] = t
    if 'CTRL' in components and trig['T_multi']:
        c = second.run(client, rp, provider, model, attempt)
        if c.get('candidate'):
            c['verify'] = _verify(client, rp, c['candidate'], model, attempt, 'verify_CTRL')
        out['CTRL'] = c
    if 'CB' in components and trig['T_confirm']:
        cbs = []
        for t in trig['T_confirm'][:2]:
            c = confirm.run(client, row, rp, t, model, attempt)
            if c.get('candidate'):
                c['verify'] = _verify(client, rp, c['candidate'], model, attempt, 'verify_CB', extra_evidence=c['candidate']['extra_evidence'])
            cbs.append(c)
        out['CB'] = cbs
    return out


def comp(rec, k):
    """[(candidate, verified SUPPORTED)] for component k."""
    x = rec.get(k)
    xs = x if isinstance(x, list) else [x] if x else []
    return [(c['candidate'], (c.get('verify') or {}).get('verdict') == 'SUPPORTED') for c in xs if c.get('candidate')]


def base_accusation(rec):
    adm = rec.get('A_adm2') or {}
    if rec['A'].get('guard_error'):
        g = [r for r in rec['A']['reasons'] if r['origin'] == 'GUARD']
        return dict(origin='GUARD', target_id=g[0]['target_id'] if g else None, text='; '.join(r['text'] for r in g)[:1500])
    if adm.get('decision') == 'ERROR':
        return dict(origin='A_adm2', target_id=adm.get('target_id'), text=adm.get('reason') or '')
    return None


def decide_v4(rec):
    """Arm -> (prediction 0/1, accusation dict or None)."""
    acc0 = base_accusation(rec)

    def acc_of(k, mode='verified'):
        """mode: verified | mechanical (code-proven admitted without verifier, others verified) | strict (only candidates
        whose relation is fixed by code, i.e. DF4 self-checks, skip the verifier) | raw."""
        for c, ok in comp(rec, k):
            if mode == 'raw' or ok or (mode == 'mechanical' and c.get('code_proven')) or (mode == 'strict' and c.get('relation_by_code')):
                return dict(origin=k, kind=c.get('kind'), code_proven=bool(c.get('code_proven')), target_id=c['target_id'],
                            text=(c.get('requirement') or '') + ' — ' + c['reason'])
        return None
    out = {'A': acc0}
    for k, arm in (('DF4', 'A_DF'), ('Ems', 'A_Ems'), ('AT', 'A_AT'), ('CTRL', 'A_CTRL'), ('CB', 'A_CB_shadow')):
        out[arm] = acc0 or acc_of(k)
        out[arm + '_raw'] = acc0 or acc_of(k, 'raw')
    out['A_DF_mech'] = acc0 or acc_of('DF4', 'mechanical')
    out['A_Ems_mech'] = acc0 or acc_of('Ems', 'mechanical')
    out['V4'] = acc0 or acc_of('DF4') or acc_of('Ems') or acc_of('AT')
    out['V4_mechanical'] = acc0 or acc_of('DF4', 'mechanical') or acc_of('Ems', 'mechanical') or acc_of('AT')
    out['V4_mech_strict'] = acc0 or acc_of('DF4', 'strict') or acc_of('Ems') or acc_of('AT')
    out['V4_raw'] = acc0 or acc_of('DF4', 'raw') or acc_of('Ems', 'raw') or acc_of('AT', 'raw')
    return {k: (int(v is not None), v) for k, v in out.items()}
