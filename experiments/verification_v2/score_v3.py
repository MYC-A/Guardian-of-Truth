"""Scorer for architecture V3 (amendment 4). Same judge (ministral-14b-2512, integrated-v1 JUDGE_PROMPT, cached)
and verdict store as score.py. Rules R1-R4 are computed vs A_adm2 on the same rows/rep.
  python -m experiments.verification_v2.score_v3 judge|report --set lb3_long --rep 1 --tag _v3"""
import argparse, json
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

from guardian_truth.integrated import Transport
from guardian_truth.verification.v3 import decide_v3
from experiments.integrated_v1.score import JUDGE_PROMPT, JUDGE_MODEL
from experiments.verification_v2.run import paced
from experiments.verification_v2.score import OUT, gold, jkey, prf, verdicts, sign_p

ARMS = ('A_adm2', 'Gc', '+E', '+DF', '+CB', 'V3', 'V3m', '+E_raw', '+DF_raw', '+CB_raw', 'V3_raw')
COMPS = ('E', 'DF', 'CB')
TARGETED = {'prose_date', 'prose_arithmetic', 'chronology_confirmation', 'later_call_violation'}


def load(name, rep, tag):
    recs = {}
    for line in (OUT / 'runs' / name / f'rep{rep}{tag}.jsonl').read_text().splitlines():
        r = json.loads(line)
        recs[r['id']] = r
    return recs


def cands(rec):
    for k in COMPS:
        x = rec.get(k)
        for c in (x if isinstance(x, list) else [x] if x else []):
            if c.get('candidate'):
                yield k, c['candidate'], (c.get('verify') or {}).get('verdict')


def ctext(c):
    return (c.get('requirement') or '') + ' — ' + c['reason']


def judge(name, rep, tag, max_calls=700):
    g, recs = gold(name), load(name, rep, tag)
    t = Transport('mistral', JUDGE_MODEL, OUT / 'cache' / 'judge', max_calls=max_calls, retry_failed=3, sender=paced)
    store = OUT / 'judge' / 'verdicts.jsonl'
    done = {json.loads(x)['key'] for x in store.read_text().splitlines()} if store.exists() else set()
    jobs = {}
    for i, rec in recs.items():
        if g[i]['label'] != 1 or not g[i].get('cause') or 'error' in rec:
            continue
        texts = [acc['text'] for p, acc in decide_v3(rec).values() if p and acc['origin'] != 'GUARD' and acc['text']]
        texts += [ctext(c) for _, c, _ in cands(rec)]
        for x in texts:
            k = jkey(x, g[i]['cause'])
            if k not in done:
                jobs[k] = (x, g[i]['cause'])

    def one(item):
        k, (text, cause) = item
        msg = json.dumps(dict(gold_explanation=cause, verifier=dict(reason=text)), ensure_ascii=False)
        req = dict(model=JUDGE_MODEL, temperature=0, max_tokens=600, response_format=dict(type='json_object'),
                   messages=[dict(role='system', content=JUDGE_PROMPT), dict(role='user', content=msg)])
        r = t.call(req, tag='judge')
        try:
            v = json.loads(r['content'])['match']
        except Exception:
            v = None
        if v:
            with open(store, 'a') as f:
                f.write(json.dumps(dict(key=k, match=v)) + '\n')
    with ThreadPoolExecutor(2) as ex:
        list(ex.map(one, jobs.items()))
    print('judge jobs', len(jobs), t.counts)


def report(name, rep, tag, quiet=False):
    g, recs, V = gold(name), load(name, rep, tag), verdicts()
    ids = [i for i in recs if i in g and 'error' not in recs[i]]
    dec = {i: decide_v3(recs[i]) for i in ids}

    def correct(i, arm):
        p, acc = dec[i][arm]
        if not p or g[i]['label'] != 1:
            return False
        if acc['origin'] == 'GUARD':
            return True
        return V.get(jkey(acc['text'], g[i].get('cause') or '')) == 'SAME'
    strata = {'all': ids}
    if any(g[i].get('family') in TARGETED for i in ids):
        strata['general'] = [i for i in ids if g[i]['family'] not in TARGETED]
        strata['targeted'] = [i for i in ids if g[i]['family'] in TARGETED]
    out = dict(set=name, rep=rep, tag=tag, rows=len(ids), errors=sum('error' in r for r in recs.values()), strata={})
    for sname, sids in strata.items():
        so = {}
        for arm in ARMS:
            pred = {i: dec[i][arm][0] for i in sids}
            m = prf(pred, g)
            gain = [i for i in sids if pred[i] and not dec[i]['A_adm2'][0] and g[i]['label'] == 1]
            cgain = [i for i in gain if correct(i, arm)]
            nfp = [i for i in sids if pred[i] and not dec[i]['A_adm2'][0] and g[i]['label'] == 0]
            so[arm] = dict(**m, cause_correct_tp=sum(correct(i, arm) for i in sids), gain=len(gain), gain_cause_correct=len(cgain),
                           new_fp=len(nfp), sign_p=sign_p(len(gain), len(nfp)),
                           gain_ids=[f"{i}:{g[i].get('case')}" + ('' if i in cgain else '(cause≠)') for i in gain],
                           fp_ids=[f"{i}:{g[i].get('case')}" for i in nfp])
        out['strata'][sname] = so
    ver = defaultdict(Counter)                      # §6 verifier criterion per component
    for i in ids:
        for k, c, v in cands(recs[i]):
            if g[i]['label'] == 0:
                ver[k]['false'] += 1
                ver[k]['false_rejected'] += int(v != 'SUPPORTED')
            else:
                same = V.get(jkey(ctext(c), g[i].get('cause') or '')) == 'SAME'
                ver[k]['true_same' if same else 'true_notsame'] += 1
                ver[k]['true_same_kept' if same else 'true_notsame_kept'] += int(v == 'SUPPORTED')
    tot = sum(ver.values(), Counter())
    out['verifier'] = {k: dict(v) for k, v in ver.items()}
    out['verifier']['all'] = dict(tot, useful=bool(tot['false'] and tot['true_same'] and tot['false_rejected'] / tot['false'] >= .5
                                                    and tot['true_same_kept'] / tot['true_same'] >= .7))
    trig = Counter()
    for i in ids:
        t = recs[i].get('triggers')
        if t is None:
            trig['base_error_or_skipped'] += 1
            continue
        lab = g[i]['label']
        trig[f'multi_{lab}'] += bool(t['T_multi']); trig[f'calc_{lab}'] += bool(t['T_calc']); trig[f'confirm_{lab}'] += bool(t['T_confirm'])
    out['triggers'] = dict(trig)
    calls = Counter()
    for i in ids:
        r = recs[i]
        calls['A'] += r['A']['cost']['calls']
        for k, c, v in cands(r):
            calls['verify_' + k] += 1
        calls['E'] += 2 * bool(r.get('E') and r['E'].get('extract'))
        calls['DF'] += bool(r.get('DF'))
        calls['CB'] += sum(1 for c in r.get('CB') or [] if c.get('step'))
    out['calls'] = dict(calls)
    path = OUT / 'reports' / f'{name}_rep{rep}{tag}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    if not quiet:
        for s, so in out['strata'].items():
            print('--', s)
            for arm, m in so.items():
                print(f"  {arm:8s} tp={m['tp']:2d} fp={m['fp']:2d} F1={m['F1']:.3f} ccTP={m['cause_correct_tp']:2d} gain={m['gain']}/{m['gain_cause_correct']}cc newFP={m['new_fp']} {m['gain_ids']} FP{m['fp_ids']}")
        print('verifier', json.dumps(out['verifier'], ensure_ascii=False))
        print('triggers', out['triggers'], 'calls', out['calls'])
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('stage', choices=['judge', 'report'])
    ap.add_argument('--set', required=True)
    ap.add_argument('--rep', type=int, default=1)
    ap.add_argument('--tag', default='_v3')
    a = ap.parse_args()
    judge(a.set, a.rep, a.tag) if a.stage == 'judge' else report(a.set, a.rep, a.tag)
