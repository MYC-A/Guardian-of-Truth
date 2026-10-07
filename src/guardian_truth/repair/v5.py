"""Universal-repair runner (docs/universal_repair/PROTOCOL.md). One record per (row, arm flags):
A (frozen guard request) decides first exactly as V4; otherwise every triggered component produces a LIST of
candidates with contract receipts; a bounded verification queue checks them; the decision is the logical OR of
SUPPORTED verdicts (aggregation), the explanation is chosen separately (selection). Flags select the repairs:
  exec evidence df_scope df_copy df_entity df_overflow  pure fixes      pool     all candidates, queue K
  witness  counter-evidence verifier bundle + technical-failure receipt   confirm  CB with confirm5 (shadow)
Without flags the record reproduces V4 (same requests, same first-candidate choice)."""
from __future__ import annotations

import json
import re

from ..integrated import ReviewConfig, review
from ..integrated.transport import sha
from ..verification import alltarget, confirm, df, df4, ems, verifier
from ..verification.admission import interpret_v2
from ..verification.common import call, norm_ws, quote_q2, request, step_record, quote_fragments_ok, schema_errors, transport_failure
from ..integrated.reviewer import decode_reply
from ..verification.pipeline import packet_for
from ..verification.proof import execute as execute_v4, leaf_quote_ok, texts_of
from . import confirm5, df5, evidence as Ev, proof5

VERSION = 'guardian-universal-repair-v5'
FIXES = frozenset({'exec', 'evidence', 'df_scope', 'df_copy', 'df_entity', 'df_overflow'})
ARMS = {'V4r': frozenset(), 'R_fix': FIXES, 'R_pool': frozenset({'pool'}), 'R_wit': frozenset({'witness'}),
        'R_df': frozenset({'df_scope', 'df_copy', 'df_entity', 'df_overflow'}), 'R_comb': FIXES | {'pool', 'witness'}}
K_QUEUE = 4


# ---------------------------------------------------------------- verifier (contract 5 input)
AFF = confirm.AFFIRM
IDLIKE = re.compile(r'(?<![\w#-])#?[A-Za-z]{0,4}-?\d[\w-]{1,}')


def _call_tokens(packet, target_id):
    t = next((x for x in packet['current_targets'] if x['source_id'] == target_id), None)
    if t is None:
        return set()
    toks = set(IDLIKE.findall(t['text'] or ''))
    a = ems._call_args(t.get('text'))
    for v in ems._leaves(a or {}):
        if isinstance(v, str) and len(v) >= 4:
            toks.add(v)
    return {x for x in toks if len(x) >= 3}


def witness(packet, cand, n, cap=6, width=1500):
    """Counter-evidence closure: besides cited + recent-4, add older events that can REFUTE the claim: tool results
    that mention the target's identifiers/values, and user turns that affirm, retract or state details."""
    have = {e['source_id'] for e in n['evidence']} | {t['source_id'] for t in n['current_move']}
    toks = _call_tokens(packet, cand['target_id']) | set(IDLIKE.findall((cand.get('reason') or '') + ' ' + (cand.get('requirement') or '')))
    hist = sorted(packet['history'], key=lambda r: (r['event'] if r['event'] is not None else -1))
    pick = []
    for h in reversed(hist):
        if h['source_id'] in have:
            continue
        txt = h.get('text') or ''
        if h.get('kind') == 'result' and any(tok in txt for tok in toks):
            pick.append(h)
        elif h.get('role') == 'user' and h.get('kind') == 'text' and (AFF.search(norm_ws(txt)) or confirm.RETRACT.search(txt) or any(tok in txt for tok in toks)):
            pick.append(h)
        if len(pick) >= cap:
            break
    keep = ('source_id', 'role', 'kind', 'tool', 'text')
    add = [{k: (h.get(k)[:width] if k == 'text' and h.get(k) else h.get(k)) for k in keep} for h in sorted(pick, key=lambda r: r['event'] if r['event'] is not None else -1)]
    return dict(n, evidence=n['evidence'] + add), [h['source_id'] for h in add]


def verify(client, rp, cand, model, attempt, tag, flags, extra_evidence=None):
    """V4 verifier request when 'witness' is off (byte-identical; stored replies replay); strict quote admission when
    'evidence' is on. -> step dict with verification_status."""
    def once(att):
        n = verifier.narrow(rp, cand, extra_evidence=extra_evidence)
        added = []
        if 'witness' in flags:
            n, added = witness(rp, cand, n)
        n = verifier._squash(n)
        req = request(model, verifier.SYSTEM, n, verifier.SCHEMA, 'violation_verifier', max_tokens=900)
        rec, value, _ = call(client, req, att, tag)
        st = step_record(rec, tag, req)
        st.update(candidate_origin=cand.get('origin'), witness_added=added)
        if rec.get('finish_reason') == 'error' and not transport_failure(dict(rec, finish_reason=None)):
            # A failed completion is never parsed as a verdict, but retains the
            # pre-existing bounded technical retry. HTTP quota/auth failures do not.
            st.update(admission='COMPLETION_FAILURE', verdict=None)
            return st
        if rec.get('content') is None:
            st.update(admission='NOT_EXECUTED' if (rec.get('transport') or {}).get('status') == 'NOT_EXECUTED_OFFLINE' else 'TRANSPORT_FAILURE', verdict=None)
            return st
        if transport_failure(rec):
            st.update(admission='TRANSPORT_FAILURE', verdict=None)
            return st
        if value is None or value.get('verdict') not in ('SUPPORTED', 'REFUTED', 'UNRESOLVED'):
            st.update(admission='INVALID_JSON', verdict=None)
            return st
        pol = [p['text'] for p in n['policy']]
        evs = [e['text'] for e in n['evidence']] + [t['text'] for t in n['current_move']] + [d['text'] for d in n['declarations']]
        if 'evidence' in flags:
            pq, eq = Ev.ok_any(value.get('policy_quote'), pol), Ev.ok_any(value.get('evidence_quote'), evs)
            if not eq:
                eq = Ev.pieces_ok(value.get('evidence_quote'), evs)
        else:
            pq, eq = quote_q2(value.get('policy_quote'), pol), quote_q2(value.get('evidence_quote'), evs)
            if not eq:
                eq = verifier.pieces_ok(value.get('evidence_quote'), evs, quote_q2)
        if not pq and not cand.get('policy_source_ids') and cand.get('origin') == 'DF4':
            pq = norm_ws(value.get('policy_quote')).strip(' ."\'') == norm_ws(cand.get('requirement')).strip(' ."\'')
        verdict = value['verdict']
        st.update(admission='ADMITTED', raw_verdict=verdict, policy_quote_ok=pq, evidence_quote_ok=eq, analysis=value.get('analysis'))
        if verdict == 'SUPPORTED' and not (pq and eq):
            verdict, st['downgraded'] = 'UNRESOLVED', 'QUOTE_NOT_VERIFIED'
        st['verdict'] = verdict
        return st
    v = once(attempt)
    if v.get('admission') in ('INVALID_JSON', 'COMPLETION_FAILURE'):
        v2 = once(attempt + 100)
        v2['first_invalid'] = {k: v.get(k) for k in ('key', 'finish_reason', 'admission')}
        v = v2
    v['verification_status'] = (v['verdict'] if v.get('verdict') else 'NOT_EXECUTED' if v.get('admission') == 'NOT_EXECUTED'
                                else 'TECHNICAL_FAILURE')
    return v


# ---------------------------------------------------------------- components
def ems_run(client, packet, model, attempt, row, fallback, flags):
    """V4 Ems requests (E1, E2 unchanged); evaluation with proof5 when 'exec'/'evidence'; all candidates kept."""
    st = dict(tag='ems5', fallback_sources=[dict(source_id=f['source_id'], origin=f['origin']) for f in fallback])
    pk = dict(packet, normative_sources=packet['normative_sources'] + list(fallback)) if fallback else packet
    rec1, v1, st['extract'] = ems._e1(client, pk, model, attempt)
    if rec1.get('content') is None:
        st.update(admission=_miss(rec1), candidates=[])
        return st
    if not v1 or not isinstance(v1.get('requirements'), list):
        st.update(admission='INVALID_JSON_EXTRACT', candidates=[])
        return st
    pol = {s['source_id']: s['text'] for s in pk['normative_sources']}
    tids = [t['source_id'] for t in pk['current_targets']]
    reqs = []
    for r in v1['requirements']:
        if r.get('target_id') in tids and r.get('policy_source_id') in pol and quote_fragments_ok(r.get('policy_quote'), pol[r['policy_source_id']]):
            reqs.append(dict(req_id=f'R{len(reqs) + 1}', **{k: r[k] for k in ('target_id', 'policy_source_id', 'policy_quote', 'requirement')}))
    st.update(n_requirements=len(reqs), requirements=reqs)
    if not reqs:
        st.update(admission='NO_VERIFIED_REQUIREMENTS', candidates=[])
        return st
    now = df.now_of(pk, row)
    user = dict(pk, requirements=reqs, reference_now=now[0].isoformat(sep=' ', timespec='minutes') if now else None)
    req2 = request(model, ems.E2, user, ems.schema2(pk, reqs, []), 'proof_plan', max_tokens=2600)
    rec2, v2, _ = call(client, req2, attempt, 'ems_plan')
    st['plan_step'] = step_record(rec2, 'ems_plan', req2)
    if rec2.get('content') is None:
        st.update(admission=_miss(rec2), candidates=[])
        return st
    if not v2 or not isinstance(v2.get('checks'), list):
        st.update(admission='INVALID_JSON_PLAN', candidates=[])
        return st
    texts = texts_of(pk)
    nd = now[0].date() if now else None
    byid = {r['req_id']: r for r in reqs}
    fixed = 'exec' in flags or 'evidence' in flags
    checks, proofs, sems = [], [], []
    for c in v2['checks']:
        r = byid.get(c.get('req_id'))
        if r is None:
            continue
        item = dict(req_id=c['req_id'], mode=c.get('mode'), raw_status=c.get('status'), operation=c.get('operation'))
        if c.get('mode') == 'PROOF':
            plan = dict(operation=c.get('operation'), target_ids=c.get('target_ids') or [r['target_id']], operands=c.get('operands'))
            ptxt = _policy_context(r, pol)
            res = proof5.execute(plan, texts, tids, nd, policy_text=ptxt) if fixed else execute_v4(plan, texts, tids, nd)
            item['execution'] = res
            pol_err = ems.polarity_error(res.get('operation') or c.get('operation'), r)
            model_says = c.get('status')
            if fixed and (res.get('receipt') or {}).get('orientation') == 'REORIENTED_FROM_POLICY':
                model_says = None              # the model's status refers to the opposite orientation
            if res['status'] == 'VIOLATED' and model_says == 'SATISFIED':
                item['status'], item['note'] = 'UNRESOLVED', 'CONTRADICTION_CODE_VIOLATED_MODEL_SATISFIED'
            elif res['status'] == 'VIOLATED' and pol_err:
                item['status'], item['note'] = 'UNRESOLVED', pol_err
            elif res['status'] == 'VIOLATED':
                item['status'] = 'VIOLATED'
                proofs.append((r, c, res))
            else:
                item['status'] = 'SATISFIED' if res['status'] == 'HOLDS' else 'UNRESOLVED'
                item['note'] = res.get('note')
        elif c.get('mode') == 'SEMANTIC':
            ev = c.get('evidence') or []
            chk = (lambda q, t: Ev.ok(q, t)) if 'evidence' in flags else leaf_quote_ok
            ok = [bool(texts.get(e.get('source_id')) and chk(e.get('quote'), texts[e['source_id']])) for e in ev]
            item.update(evidence_ok=ok)
            if c.get('status') == 'VIOLATED':
                if ev and all(ok):
                    item['status'] = 'VIOLATED'
                    sems.append((r, c))
                else:
                    item['status'], item['note'] = 'UNRESOLVED', 'EVIDENCE_NOT_VERIFIED'
            else:
                item['status'] = c.get('status')
        else:
            item['status'] = 'NOT_APPLICABLE'
        checks.append(item)
    cands = []
    for r, c, res in proofs:
        tgt = (c.get('target_ids') or [r['target_id']])[-1]
        cd = dict(origin='Ems', kind='STRUCTURED_PROOF', code_proven=True, target_id=tgt, requirement=r['requirement'],
                  policy_source_ids=[r['policy_source_id']], evidence_source_ids=sorted({o['source_id'] for o in c['operands'] if o['source_id'] not in pol}) or [tgt],
                  reason=f"{c.get('reason') or ''} Code-executed proof ({res['operation']}): {res['detail']} — the condition required by the policy does not hold.".strip(),
                  proof=dict(operation=res['operation'], leaves=res['leaves'], detail=res['detail']))
        cd['receipt'] = res.get('receipt')
        cd['certificate'] = bool(fixed and proof5.certificate(res))
        cands.append(cd)
    for r, c in sems:
        cands.append(dict(origin='Ems', kind='SEMANTIC', code_proven=False, target_id=r['target_id'], requirement=r['requirement'],
                          policy_source_ids=[r['policy_source_id']], evidence_source_ids=[e['source_id'] for e in c['evidence']],
                          reason=c.get('reason') or '', certificate=False))
    if fallback:
        for cd in cands:
            cd['extra_policy'] = [dict(source_id=f['source_id'], text=f['text']) for f in fallback if f['source_id'] in cd['policy_source_ids']]
    st.update(admission='ADMITTED', checks=checks, candidates=cands, structured=len(proofs), semantic=len(sems))
    return st


def _policy_context(r, pol):
    """The policy sentence(s) containing the requirement's quote, for orientation/applicability receipts."""
    text = pol.get(r['policy_source_id']) or ''
    q = norm_ws(r.get('policy_quote') or '')
    t = norm_ws(text)
    i = t.lower().find(q.lower()[:60]) if q else -1
    if i < 0:
        return q + ' ' + (r.get('requirement') or '')
    a = max(t.rfind('. ', 0, i), t.rfind('\n', 0, i)) + 1
    b = t.find('. ', i + len(q))
    return t[a:(b + 1 if b >= 0 else len(t))]


def at_run(client, packet, model, attempt, flags):
    st = dict(tag='alltarget5')
    req = request(model, alltarget.SYSTEM, packet, alltarget.schema(packet), 'all_target_review', max_tokens=2200)
    rec, v, _ = call(client, req, attempt, 'alltarget')
    st['step'] = step_record(rec, 'alltarget', req)
    if rec.get('content') is None:
        st.update(admission=_miss(rec), candidates=[])
        return st
    if transport_failure(rec):
        st.update(admission='TRANSPORT_FAILURE', candidates=[])
        return st
    tids = [t['source_id'] for t in packet['current_targets']]
    # AT is an independent-item contract: an invalid item cannot certify anything,
    # but must not erase a different valid target. Decode only complete JSON and
    # validate its envelope before isolating items under the SAME requested schema.
    if v is None:
        raw, decoded, _ = decode_reply(rec.get('content'))
        envelope = dict(alltarget.schema(packet))
        envelope['properties'] = dict(envelope['properties'])
        envelope['properties']['targets'] = dict(envelope['properties']['targets'])
        envelope['properties']['targets'].pop('items', None)
        if not decoded or schema_errors(raw, envelope):
            st.update(admission='INVALID_JSON', candidates=[])
            return st
        v = raw
    items = v.get('targets') if isinstance(v, dict) else None
    if not isinstance(items, list):
        st.update(admission='INVALID_JSON', candidates=[])
        return st
    item_schema = alltarget.schema(packet)['properties']['targets']['items']
    known_ids = [x.get('target_id') for x in items if isinstance(x, dict) and isinstance(x.get('target_id'), str)]
    duplicated = sorted({t for t in known_ids if known_ids.count(t) > 1})
    invented = sorted({t for t in known_ids if t not in tids})
    quarantined, valid_items = [], []
    for index, item in enumerate(items):
        errors = schema_errors(item, item_schema)
        tid = item.get('target_id') if isinstance(item, dict) else None
        if errors or tid in duplicated:
            quarantined.append(dict(index=index, target_id=tid, errors=errors,
                                    reason='DUPLICATED_TARGET' if tid in duplicated else 'INVALID_ITEM_SCHEMA'))
        else:
            valid_items.append(item)
    checked_ids = {x['target_id'] for x in valid_items}
    missing = [t for t in tids if t not in known_ids]
    unchecked = [t for t in tids if t not in checked_ids]
    cov = dict(complete=not unchecked and not quarantined, missing=missing,
               duplicated=duplicated, invented=invented, unchecked=unchecked)
    texts = texts_of(packet)
    pol = {s['source_id']: s['text'] for s in packet['normative_sources']}
    strict = 'evidence' in flags
    rows, cands = [], []
    order = {t: i for i, t in enumerate(tids)}
    for x in sorted(valid_items, key=lambda x: order[x['target_id']]):
        r = dict(target_id=x.get('target_id'), status=x.get('status'))
        if x.get('status') == 'ERROR':
            ptexts = [pol[p] for p in x.get('policy_source_ids') or [] if p in pol]
            r['policy_ok'] = bool(ptexts) and (Ev.ok_any(x.get('policy_quote'), ptexts) if strict else quote_q2(x.get('policy_quote'), ptexts))
            chk = Ev.ok if strict else leaf_quote_ok
            r['evidence_ok'] = [bool(texts.get(e.get('source_id')) and chk(e.get('quote'), texts[e['source_id']])) for e in x.get('evidence') or []]
            r['admitted'] = r['policy_ok'] and any(r['evidence_ok'])
            if r['admitted']:
                ev = [e['source_id'] for e, ok in zip(x.get('evidence') or [], r['evidence_ok']) if ok]
                cands.append(dict(origin='AT', target_id=x['target_id'], requirement=x.get('policy_quote') or '', reason=x.get('reason') or '',
                                  policy_source_ids=[p for p in x.get('policy_source_ids') or [] if p in pol], evidence_source_ids=ev,
                                  code_proven=False, certificate=False))
        rows.append(r)
    rows += [dict(target_id=t, status='UNCHECKED', admitted=False,
                  reason='DUPLICATED_TARGET' if t in duplicated else 'MISSING_OR_INVALID_TARGET') for t in unchecked]
    rows.sort(key=lambda x: order[x['target_id']])
    st.update(admission='ADMITTED' if cov.get('complete') else 'COVERAGE_INCOMPLETE', coverage=cov,
              targets=rows, quarantined=quarantined, candidates=cands)
    return st


def _miss(rec):
    return 'NOT_EXECUTED' if (rec.get('transport') or {}).get('status') == 'NOT_EXECUTED_OFFLINE' else 'TRANSPORT_FAILURE'


def cb_run(client, row, packet, trig, model, attempt):
    """CB with confirm5 binding/compare (shadow); map request identical to V4 when the binding is identical."""
    orig_b, orig_c = confirm.binding, confirm.compare
    try:
        confirm.binding, confirm.compare = confirm5.binding, confirm5.compare
        st = confirm.run(client, row, packet, trig, model, attempt)
    finally:
        confirm.binding, confirm.compare = orig_b, orig_c
    c = st.get('candidate')
    st['candidates'] = [dict(c, certificate=False)] if c else []
    return st


# ---------------------------------------------------------------- run + decide
PRIORITY = {('Ems', 'cert'): 0, ('DF4', 'code'): 1, ('DF4', 'bound'): 2, ('Ems', 'STRUCTURED_PROOF'): 3, ('Ems', 'SEMANTIC'): 4, ('AT', None): 5, ('CB', None): 6}


def _prio(c):
    if c['origin'] == 'Ems':
        return PRIORITY[('Ems', 'cert')] if c.get('certificate') else PRIORITY[('Ems', c.get('kind'))]
    if c['origin'] == 'DF4':
        return PRIORITY[('DF4', 'code')] if c.get('relation_by_code') else PRIORITY[('DF4', 'bound')]
    return PRIORITY[(c['origin'], None)]


def run_v5(row, client, *, flags=frozenset(), provider='mistral', model='ministral-14b-2512', budget=20000, attempt=0, with_cb=False):
    flags = frozenset(flags)
    cfg = ReviewConfig.profile('guard', provider=provider, model=model, budget_bytes=budget, attempt=attempt, admission='v1')
    a = review(row['prompt'], row['response'], cfg, client=client)
    out = dict(version=VERSION, flags=sorted(flags), A=dict(final=a['final_decision'], binary=a['binary'], owner=a['decision_owner'],
               guard_error=a['guard']['established_error'], reasons=a['reasons'], steps=a['steps']))
    rp = packet_for(row, budget)
    if rp is None:
        out['skipped'] = 'NO_PACKET'
        return out
    assert sha(rp) == a['packet']['packet_sha256'], 'packet drift between A and V5'
    s0 = next((s for s in a['steps'] if s.get('tag') == 'review'), None)
    adm = dict(decision=None, admission='NO_REVIEW_STEP')
    if s0 is not None and s0.get('raw_content') is not None:
        v2 = interpret_v2(s0['raw_content'], rp)
        adm = dict(admission=v2['admission'], decision=v2['decision'])
        if v2['admitted']:
            adm.update(target_id=v2['admitted']['regulated_action']['target_id'], reason=v2['admitted']['reason'])
    out['A_adm2'] = adm
    out['base_error'] = adm.get('decision') == 'ERROR' or bool(a['guard']['established_error'])
    if out['base_error'] or not rp['current_targets'] or not rp['normative_sources']:
        out['triggers'] = None
        return out
    et = ems.trigger(rp, row)
    trig = dict(T_multi=len(rp['current_targets']) >= 2, T_calc=df.trigger(rp, row), T_quant=et['quant'],
                T_confirm=(confirm5.trigger(rp, row) if 'confirm' in flags else confirm.trigger(rp, row)) if with_cb else [])
    out['triggers'] = trig
    comps = {}
    if trig['T_calc']:
        comps['DF4'] = df5.run(client, rp, model, attempt, row=row, flags=flags)
    if trig['T_multi'] or trig['T_quant']:
        comps['Ems'] = ems_run(client, rp, model, attempt, row, et['fallback'], flags)
    if trig['T_multi']:
        comps['AT'] = at_run(client, rp, model, attempt, flags)
    if with_cb:
        cbs = [cb_run(client, row, rp, t, model, attempt) for t in trig['T_confirm'][:2]]
        if cbs:
            comps['CB'] = dict(tag='cb5', runs=cbs, candidates=[c for x in cbs for c in x['candidates']])
    # queue: V4 = first candidate of each component; pool = all candidates, priority order, bounded K
    queue = []
    for k in ('DF4', 'Ems', 'AT', 'CB'):
        cs = (comps.get(k) or {}).get('candidates') or []
        if 'pool' in flags:
            queue += [(k, i, c) for i, c in enumerate(cs)]
        elif cs:
            queue.append((k, 0, cs[0]))
    if 'pool' in flags:
        seen, q2 = set(), []
        for k, i, c in sorted(queue, key=lambda x: (_prio(x[2]), ('DF4', 'Ems', 'AT', 'CB').index(x[0]), x[1])):
            # Only identical candidate contracts are duplicates. Different witnesses,
            # proof plans, scopes or reasons remain independent hypotheses.
            sig = json.dumps(c, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
            if sig not in seen:
                seen.add(sig)
                q2.append((k, i, c))
        queue = q2
    pool = []
    for n, (k, i, c) in enumerate(queue):
        item = dict(component=k, index=i, candidate=c, priority=_prio(c))
        if 'pool' in flags and n >= K_QUEUE:
            item['verification_status'] = 'UNCHECKED_QUEUE_BOUND'
        else:
            tag = {'DF4': 'verify_DF4', 'Ems': 'verify_Ems', 'AT': 'verify_AT', 'CB': 'verify_CB'}[k]
            v = verify(client, rp, c, model, attempt, tag, flags, extra_evidence=c.get('extra_evidence'))
            item['verify'] = v
            item['verification_status'] = v['verification_status']
        pool.append(item)
    out['components'] = comps
    out['pool'] = pool
    return out


def decide(rec, mech=False, alone=False, cb=False):
    """-> (0/1, accusation). Aggregation: ERROR iff some candidate is SUPPORTED (mech: or carries a full certificate
    and was not REFUTED). Selection: the first such candidate in queue (priority) order."""
    acc0 = None
    if not alone and rec.get('base_error'):
        A = rec['A']
        if A.get('guard_error'):
            g = [r for r in A['reasons'] if r['origin'] == 'GUARD']
            acc0 = dict(origin='GUARD', target_id=g[0]['target_id'] if g else None, text='; '.join(r['text'] for r in g)[:1500])
        else:
            adm = rec.get('A_adm2') or {}
            acc0 = dict(origin='A_adm2', target_id=adm.get('target_id'), text=adm.get('reason') or '')
        return 1, acc0
    for it in rec.get('pool') or []:
        if it['component'] == 'CB' and not cb:
            continue
        c, vs = it['candidate'], it.get('verification_status')
        if vs == 'SUPPORTED' or (mech and c.get('certificate') and vs == 'UNRESOLVED'):   # diagnostic only: verifier ran, could not decide
            return 1, dict(origin=it['component'], kind=c.get('kind'), target_id=c['target_id'], verification=vs,
                           certificate=bool(c.get('certificate')), text=(c.get('requirement') or '') + ' — ' + c['reason'])
    return 0, None
