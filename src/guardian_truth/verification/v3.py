"""Architecture V3 (amendment 4): guard_adm2 + G_closed + code-gated focused checkers + one Q2 verifier.
A (frozen guard request, admission v2) decides first; ERROR is final. Otherwise code triggers choose the
checkers: T_multi (>=2 current targets) -> E (Q2 + G_E), T_calc (prose with dates/weekdays/durations/money)
-> DF, T_confirm (call of a tool the policy ties to confirmation) -> CB. Every candidate goes to the narrow
verifier with Q2 quote admission. Arms are projections of this one record (decide_v3)."""
from __future__ import annotations

import re

from ..integrated import ReviewConfig, review
from ..integrated.declarations import check as declarations_check
from ..integrated.transport import sha
from ..source_search.store import SourceStore
from . import checklist, confirm, df, verifier
from .admission import interpret_v2
from .pipeline import packet_for

VERSION = 'guardian-v3 (amendment 4)'
CLOSED = re.compile(
    r'(?:list|set|catalog(?:ue)?|inventory) of (?:the )?(?:available )?tools (?:above |below )?is (?:complete|exhaustive|closed)'
    r'|tools? list (?:above |below )?is (?:complete|exhaustive)|\bno other tools\b|there are no other tools'
    r'|never (?:call|use|invoke) (?:a|any) tool (?:that is|which is|not) (?:not )?(?:on|in|listed)'
    r'|(?:список|перечень) (?:доступных )?инструментов (?:является )?(?:полным|полный|исчерпывающ\w*|закрыт\w*)'
    r'|других инструментов нет|никаких других инструментов|не вызыва\w* инструмент\w*,? (?:которых|которого) нет', re.I)


def closure_sentence(row):
    st = SourceStore(row)
    for e in st.history_events:
        if e.role == 'system':
            m = CLOSED.search(e.text)
            if m:
                return e.text[max(0, m.start() - 120):m.end() + 120].strip()
    return None


def g_closed(row):
    s = closure_sentence(row)
    if not s:
        return dict(closed=False, error=False)
    d = declarations_check(row, tool_universe_closed=True)
    f = [x for x in d['findings'] if x['code'] == 'unavailable_tool']
    return dict(closed=True, sentence=s, error=bool(f), complete=d['catalog']['executable_inventory_complete'],
                findings=[dict(target_id=x['target_id'], claim=x['claim']) for x in f])


def _verify(client, rp, cand, model, attempt, tag, **kw):
    """Q2 verifier; one retry (separate cache key) when the reply is not valid JSON (e.g. finish_reason 'error')."""
    v = verifier.run(client, rp, cand, model, attempt, tag=tag, quote_rule='Q2', squash_ws=True, **kw)
    if v.get('admission') == 'INVALID_JSON':
        v2 = verifier.run(client, rp, cand, model, attempt + 100, tag=tag, quote_rule='Q2', squash_ws=True, **kw)
        v2['first_invalid'] = {k: v.get(k) for k in ('key', 'finish_reason', 'admission')}
        v = v2
    return v


def run_v3(row, client, *, provider='mistral', model='ministral-14b-2512', budget=20000, attempt=0, components=('E', 'DF', 'CB')):
    cfg = ReviewConfig.profile('guard', provider=provider, model=model, budget_bytes=budget, attempt=attempt, admission='v1')   # cached A request
    a = review(row['prompt'], row['response'], cfg, client=client)
    out = dict(version=VERSION, A=dict(final=a['final_decision'], binary=a['binary'], proof=a['proof_status'], owner=a['decision_owner'],
                                     guard_error=a['guard']['established_error'], reasons=a['reasons'], steps=a['steps'], cost=a['cost']))
    rp = packet_for(row, budget)
    out['G_closed'] = g_closed(row)
    if rp is None:
        out['skipped'] = 'NO_PACKET'
        return out
    assert sha(rp) == a['packet']['packet_sha256'], 'packet drift between A and V3'
    s0 = next((s for s in a['steps'] if s.get('tag') == 'review'), None)
    adm = dict(decision=None, admission='NO_REVIEW_STEP')
    if s0 is not None and s0.get('raw_content') is not None:
        v2 = interpret_v2(s0['raw_content'], rp)
        adm = dict(admission=v2['admission'], decision=v2['decision'], actor_normalised=v2['actor_normalised'])
        if v2['admitted']:
            adm.update(target_id=v2['admitted']['regulated_action']['target_id'], reason=v2['admitted']['reason'])
    out['A_adm2'] = adm
    base = adm.get('decision') == 'ERROR' or bool(a['guard']['established_error'])
    out['base_error'] = base
    if base or not rp['current_targets'] or not rp['normative_sources']:
        out['triggers'] = None
        return out
    trig = dict(T_multi=len(rp['current_targets']) >= 2, T_calc=df.trigger(rp, row), T_confirm=confirm.trigger(rp, row))
    out['triggers'] = trig
    if 'E' in components and trig['T_multi']:
        e = checklist.run(client, rp, model, attempt, quote_rule='Q2', gate_ge=True)
        if e.get('candidate'):
            e['verify'] = _verify(client, rp, e['candidate'], model, attempt, 'verify_E')
        out['E'] = e
    if 'DF' in components and trig['T_calc']:
        d = df.run(client, rp, model, attempt, row=row)
        if d.get('candidate'):
            d['verify'] = _verify(client, rp, d['candidate'], model, attempt, 'verify_DF')
        out['DF'] = d
    if 'CB' in components and trig['T_confirm']:
        cbs = []
        for t in trig['T_confirm'][:2]:
            c = confirm.run(client, row, rp, t, model, attempt)
            if c.get('candidate'):
                c['verify'] = _verify(client, rp, c['candidate'], model, attempt, 'verify_CB', extra_evidence=c['candidate']['extra_evidence'])
            cbs.append(c)
        out['CB'] = cbs
    return out


def _comp(rec, k):
    """(candidate, verified SUPPORTED) pairs for component k."""
    x = rec.get(k)
    xs = x if isinstance(x, list) else [x] if x else []
    return [(c['candidate'], (c.get('verify') or {}).get('verdict') == 'SUPPORTED') for c in xs if c.get('candidate')]


def decide_v3(rec):
    """Arm -> (prediction 0/1, accusation dict or None)."""
    adm = rec.get('A_adm2') or {}
    guard = bool(rec['A'].get('guard_error'))
    out = {}
    if guard:
        g = [r for r in rec['A']['reasons'] if r['origin'] == 'GUARD']
        acc0 = dict(origin='GUARD', target_id=g[0]['target_id'] if g else None, text='; '.join(r['text'] for r in g)[:1500])
    elif adm.get('decision') == 'ERROR':
        acc0 = dict(origin='A_adm2', target_id=adm.get('target_id'), text=adm.get('reason') or '')
    else:
        acc0 = None
    out['A_adm2'] = acc0
    gc = rec.get('G_closed') or {}
    accg = acc0 or (dict(origin='GUARD', target_id=gc['findings'][0]['target_id'], text=gc['findings'][0]['claim']) if gc.get('error') else None)
    out['Gc'] = accg

    def acc_of(k, need_verified=True, proven_only=False):
        for c, ok in _comp(rec, k):
            if proven_only and not c.get('code_proven'):
                continue
            if ok or not need_verified:
                return dict(origin=k, target_id=c['target_id'], text=(c.get('requirement') or '') + ' — ' + c['reason'])
        return None
    for k in ('E', 'DF', 'CB'):
        out['+' + k] = accg or acc_of(k)
        out['+' + k + '_raw'] = accg or acc_of(k, need_verified=False)
    out['V3'] = accg or acc_of('E') or acc_of('DF') or acc_of('CB')
    out['V3m'] = out['V3'] or acc_of('DF', False, True) or acc_of('CB', False, True)
    out['V3_raw'] = accg or acc_of('E', False) or acc_of('DF', False) or acc_of('CB', False)
    return {k: (int(v is not None), v) for k, v in out.items()}
