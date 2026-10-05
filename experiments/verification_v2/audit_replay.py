"""Amendment 3 offline audit (no model calls): re-admit stored raw replies with Q2 quote admission, apply the
G_E consistency gate to E, and add the directional counterfactual flag. Writes runs/<set>/rep1_audit.jsonl
(and rep1_audit_s.jsonl for the Q2s sensitivity variant).
  python -m experiments.verification_v2.audit_replay --set lb2_long"""
import argparse, copy, json, re
from collections import Counter

from guardian_truth.integrated.transport import sha
from guardian_truth.verification import calc, verifier
from guardian_truth.verification.common import _clean_quote, decode_reply, norm_ws, quote_fragments_ok, request
from guardian_truth.verification.pipeline import _a_candidate, packet_for
from experiments.verification_v2.run import inputs, MODEL
from experiments.verification_v2.score import OUT, load

STR = re.compile(r'"((?:[^"\\]|\\.)*)"')


def q2(quote, texts, short_json=False, sentences=False):
    if any(quote_fragments_ok(quote, t) for t in texts):
        return True
    if sentences:                     # EXPLORATORY (not pre-registered): each sentence verbatim in the same source
        parts = [x for x in re.split(r'(?<=[.!?])\s+', norm_ws(quote)) if x.strip()]
        if len(parts) >= 2 and any(all(quote_fragments_ok(x, t) for x in parts) for t in texts):
            return True
    if short_json:
        q = _clean_quote(quote)
        return bool(q) and any(q == norm_ws(v) for t in texts for v in STR.findall(t or ''))
    return False


def reverify(st, packet, cand, short_json, stats, sentences=False):
    """Recompute the downgrade of one stored verifier step; raw verdict untouched."""
    if not st or st.get('admission') != 'ADMITTED':
        return st
    n = verifier.narrow(packet, cand)
    req = request(MODEL, verifier.SYSTEM, n, verifier.SCHEMA, 'violation_verifier', max_tokens=900)
    if sha(req) != st['request_sha256']:
        stats['verifier_NOT_REPLAYABLE'] += 1
        return dict(st, verdict=None, replay='NOT_REPLAYABLE')
    value, valid, _ = decode_reply(st['raw_content'])
    pq = q2(value.get('policy_quote'), [p['text'] for p in n['policy']], sentences=sentences)
    eq = q2(value.get('evidence_quote'), [e['text'] for e in n['evidence']] + [t['text'] for t in n['current_move']] +
            [d['text'] for d in n['declarations']], short_json, sentences)
    verdict = value['verdict']
    out = dict(st, policy_quote_ok_v1=st.get('policy_quote_ok'), evidence_quote_ok_v1=st.get('evidence_quote_ok'),
               policy_quote_ok=pq, evidence_quote_ok=eq, verdict_v1=st.get('verdict'))
    out.pop('downgraded', None)
    if verdict == 'SUPPORTED' and not (pq and eq):
        verdict, out['downgraded'] = 'UNRESOLVED', 'QUOTE_NOT_VERIFIED'
    out['verdict'] = verdict
    if out['verdict'] != out['verdict_v1']:
        stats[f"verifier_{st.get('tag')}_{out['verdict_v1']}->{verdict}"] += 1
    return out


def readmit_e(e, packet, stats):
    if not e or e.get('admission') != 'ADMITTED':
        return e
    texts = [s['text'] for k in ('normative_sources', 'history', 'declarations', 'current_targets') for s in packet[k]]
    v2, _, _ = decode_reply(e['check']['raw_content'])
    byid = {r['req_id']: r for r in e['requirements']}
    checks, cand = [], None
    for c in v2['checks']:
        if c.get('req_id') not in byid:
            continue
        status, note = c['status'], None
        ok = q2(c.get('evidence_quote'), texts)
        comp = calc._check_arith(c.get('computation'))
        cmp_ok = calc.check_comparisons(c.get('computation'))
        if status == 'VIOLATED' and not ok:
            status, note = 'UNRESOLVED', 'EVIDENCE_QUOTE_NOT_VERIFIED'
        elif status == 'VIOLATED' and comp is False:
            status, note = 'UNRESOLVED', 'COMPUTATION_WRONG'
        elif status == 'VIOLATED' and cmp_ok is False:
            status, note = 'UNRESOLVED', 'COMPARISON_FALSE'          # G_E
        checks.append(dict(req_id=c['req_id'], raw_status=c['status'], status=status, note=note, quote_ok=ok,
                           computation=c.get('computation'), computation_ok=comp, comparisons_ok=cmp_ok))
        if status == 'VIOLATED' and cand is None:
            r = byid[c['req_id']]
            cand = dict(origin='checklist', req_id=c['req_id'], target_id=r['target_id'], requirement=r['requirement'], reason=c.get('reason') or '',
                        policy_source_ids=[r['policy_source_id']], evidence_source_ids=c.get('evidence_source_ids') or [r['target_id']])
    old = e.get('candidate')
    out = dict(e, checks=checks, candidate=cand, candidate_v1=old)
    same = (old is None and cand is None) or (old and cand and old['requirement'] == cand['requirement'] and old['reason'] == cand['reason'])
    if not same:
        stats[f"E_candidate_{'none' if not old else 'cand'}->{'none' if not cand else 'cand'}"] += 1
        out['verify'] = None
        if cand:
            stats['E_needs_verifier_call'] += 1
            out['needs_verifier_call'] = True
    for c in checks:
        if c['note'] == 'COMPARISON_FALSE':
            stats['E_G_E_downgrades'] += 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--set', required=True)
    ap.add_argument('--tag', default='')
    a = ap.parse_args()
    rows = {x['id']: x for x in inputs(a.set)}
    recs = load(a.set, 1, a.tag)                  # last record per id (duplicates from transport retries collapse here)
    for short_json, sentences, suffix in ((False, False, '_audit'), (True, False, '_audit_s'), (True, True, '_audit_x')):
        stats = Counter()
        out = []
        for i, r in recs.items():
            r = copy.deepcopy(r)
            p = packet_for(rows[i], 20000)
            if p is not None and r.get('escalated'):
                for k in ('B', 'C'):
                    x = r.get(k)
                    if x and x.get('candidate') and x.get('verify'):
                        x['verify'] = reverify(x['verify'], p, x['candidate'], short_json, stats, sentences)
                if r.get('E'):
                    e = r['E']
                    if e.get('candidate') and e.get('verify'):
                        e['verify'] = reverify(e['verify'], p, e['candidate'], short_json, stats, sentences)
                    r['E'] = readmit_e(e, p, stats)
                c = r.get('C')
                if c and c.get('admission') == 'ADMITTED':
                    c['directional'] = c.get('original_status') == 'VIOLATING' and any(v.get('status') == 'COMPLIANT' for v in c.get('variant_judgements') or [])
            if p is not None and r.get('Av') and not r.get('escalated'):
                cand = _a_candidate(dict(reasons=r['A']['reasons']))
                r['Av'] = reverify(r['Av'], p, cand, short_json, stats, sentences)
            out.append(r)
        path = OUT / 'runs' / a.set / f'rep1{a.tag}{suffix}.jsonl'
        path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in out))
        print(a.set, suffix, dict(stats))


if __name__ == '__main__':
    main()
