"""verification-v2 execution of one row (protocol §2): A (frozen guard profile), then on the escalation
set (A final != ERROR) the second reviewer (B) and the counterfactual probe (C), each candidate checked by
the narrow verifier (Bv / D); on A ERROR rows owned by the model, the verifier checks A's accusation (Av,
shadow). Arm decisions are projections of this single record (arms.py), so arms share the same A call."""
from __future__ import annotations

from ..evidence_packer import PackerConfig, pack, resolve
from ..integrated import ReviewConfig, review, reviewer
from ..integrated.transport import sha
from ..source_search.store import SourceStore
from . import checklist, probe, second, variants, verifier
from .admission import interpret_v2

VERSION = 'guardian-verification-v2'


def packet_for(row, budget):
    p = pack(row, PackerConfig(budget_bytes=budget))
    if p.get('failure'):
        return None
    resolve(p, row)
    return reviewer.review_packet(p, p.get('mode') == 'FULL_INPUT')


def _a_candidate(a_res):
    for r in a_res['reasons']:
        if r['origin'] in ('review', 'controller') and r.get('decision') == 'ERROR':
            return dict(origin='A', target_id=r['target_id'], requirement=None, reason=r['text'],
                        policy_source_ids=r['norms'], evidence_source_ids=r['source_refs'])
    return None


def run_row(row, client, *, provider='mistral', model='ministral-14b-2512', budget=20000, attempt=0, mechanisms=('B', 'C')):
    cfg = ReviewConfig.profile('guard', provider=provider, model=model, budget_bytes=budget, attempt=attempt, admission='v1')   # frozen A
    a = review(row['prompt'], row['response'], cfg, client=client)
    out = dict(version=VERSION, A=dict(final=a['final_decision'], binary=a['binary'], proof=a['proof_status'], owner=a['decision_owner'],
                                     guard_error=a['guard']['established_error'], reasons=a['reasons'], steps=a['steps'], cost=a['cost']))
    rp = packet_for(row, budget)
    if rp is None or not rp['current_targets'] or not rp['normative_sources']:
        out['skipped'] = 'NO_PACKET_OR_TARGET_OR_POLICY'
        return out
    assert sha(rp) == a['packet']['packet_sha256'], 'packet drift between A and v2'
    # admission v2 replay of A's own reply (no new call): receipt-actor ablation
    s0 = next((s for s in a['steps'] if s.get('tag') == 'review'), None)
    if s0 is not None and s0.get('raw_content') is not None:
        v2 = interpret_v2(s0['raw_content'], rp)
        out['A_adm2'] = dict(admission=v2['admission'], decision=v2['decision'], actor_normalised=v2['actor_normalised'])
        if v2['admitted']:
            out['A_adm2'].update(target_id=v2['admitted']['regulated_action']['target_id'], reason=v2['admitted']['reason'])
    out['escalated'] = a['final_decision'] != 'ERROR'
    if out['escalated']:
        if 'B' in mechanisms:
            b = second.run(client, rp, provider, model, attempt)
            out['B'] = b
            if b['candidate']:
                out['B']['verify'] = verifier.run(client, rp, b['candidate'], model, attempt, tag='verify_B')
        if 'C' in mechanisms:
            store = SourceStore(row)
            vs = variants.build(store)
            c = probe.run(client, rp, vs, model, attempt)
            c['variants'] = [{k: v[k] for k in ('variant_id', 'target_id', 'kind', 'path', 'original', 'replacement')} for v in vs]
            out['C'] = c
            if c['candidate']:
                out['C']['verify'] = verifier.run(client, rp, c['candidate'], model, attempt, tag='verify_C')
        if 'E' in mechanisms:
            e = checklist.run(client, rp, model, attempt)
            out['E'] = e
            if e['candidate']:
                out['E']['verify'] = verifier.run(client, rp, e['candidate'], model, attempt, tag='verify_E')
    else:
        cand = _a_candidate(a)
        if cand:
            out['Av'] = verifier.run(client, rp, cand, model, attempt, tag='verify_A')
    return out
