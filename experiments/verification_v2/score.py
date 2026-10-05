"""Scorer + cause judge for verification v2 (evaluation only; gold never feeds inference).
  python -m experiments.verification_v2.score judge  --set lb_long [--rep 1]
  python -m experiments.verification_v2.score report --set lb_long [--rep 1]
Judge = ministral-14b-2512 with the unchanged integrated-v1 JUDGE_PROMPT (amendment 3), cached."""
import argparse, json
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from math import comb
from pathlib import Path

from guardian_truth.integrated import Transport
from guardian_truth.integrated.transport import sha
from guardian_truth.verification.arms import decide
from experiments.integrated_v1.score import JUDGE_PROMPT, JUDGE_MODEL
from experiments.verification_v2.run import paced

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'outputs/verification_v2'
ARMS = ('A', 'A_adm2', 'B', 'Bv', 'C', 'D', 'Av', 'Av_strict')


def gold(name):
    if name == 'valid46':
        import pandas as pd
        d = pd.read_parquet(ROOT / 'valid.parquet')
        return {r.id: dict(label=int(r.label), cause=r.explanation if isinstance(r.explanation, str) else None, family=r.id.split('__')[0],
                           target=None, pair=None) for r in d.itertuples()}
    sub = {'lb_long': 'long', 'lb_short': 'short'}[name]
    return json.loads((OUT / 'lockbox' / sub / 'GOLD_eval_only.json').read_text())


def load(name, rep):
    recs = {}
    for line in (OUT / 'runs' / name / f'rep{rep}.jsonl').read_text().splitlines():
        r = json.loads(line)
        recs[r['id']] = r
    return recs


def accusation(rec, arm):
    """The accusation that makes `arm` predict ERROR (None if the arm predicts 0)."""
    d = decide(rec)
    if not d[arm]:
        return None
    a = rec['A']
    if a['final'] == 'ERROR' and arm not in ('B', 'Bv', 'C', 'D') or a['final'] == 'ERROR':
        if a['proof'] == 'MECHANICAL_PROOF':
            g = [r for r in a['reasons'] if r['origin'] == 'GUARD']
            return dict(origin='GUARD', target_id=g[0]['target_id'] if g else None, text='; '.join(r['text'] for r in g)[:1500])
        m = [r for r in a['reasons'] if r['origin'] != 'GUARD']
        if arm == 'A_adm2' and not m:
            m = []
        return dict(origin='A', target_id=m[0]['target_id'] if m else None, text=m[0]['text'] if m else '')
    if arm == 'A_adm2':
        return dict(origin='A_adm2', target_id=None, text='(admission-v2 replay of A; reason not stored)')
    k = 'B' if arm in ('B', 'Bv') else 'C'
    c = rec[k]['candidate']
    return dict(origin=k, target_id=c['target_id'], text=(c.get('requirement') or '') + ' — ' + c['reason'])


def jkey(text, cause):
    return sha(dict(t=text, g=cause))


def judge(name, rep, max_calls=400):
    g, recs = gold(name), load(name, rep)
    t = Transport('mistral', JUDGE_MODEL, OUT / 'cache' / 'judge', max_calls=max_calls, retry_failed=3, sender=paced)
    store = OUT / 'judge' / 'verdicts.jsonl'
    store.parent.mkdir(parents=True, exist_ok=True)
    done = {json.loads(x)['key'] for x in store.read_text().splitlines()} if store.exists() else set()
    jobs = {}
    for i, rec in recs.items():
        if g[i]['label'] != 1 or not g[i].get('cause'):
            continue
        for arm in ARMS:
            acc = accusation(rec, arm)
            if acc and acc['origin'] not in ('GUARD', 'A_adm2') and acc['text']:
                k = jkey(acc['text'], g[i]['cause'])
                if k not in done:
                    jobs[k] = (acc, g[i]['cause'])
        for k2 in ('B', 'C'):                          # every true-row candidate (for verifier usefulness)
            c = (rec.get(k2) or {}).get('candidate')
            if c:
                text = (c.get('requirement') or '') + ' — ' + c['reason']
                k = jkey(text, g[i]['cause'])
                if k not in done:
                    jobs[k] = (dict(text=text), g[i]['cause'])

    def one(item):
        k, (acc, cause) = item
        msg = json.dumps(dict(gold_explanation=cause, verifier=dict(reason=acc['text'])), ensure_ascii=False)
        req = dict(model=JUDGE_MODEL, temperature=0, max_tokens=600, response_format=dict(type='json_object'),
                   messages=[dict(role='system', content=JUDGE_PROMPT), dict(role='user', content=msg)])
        rec = t.call(req, tag='judge')
        try:
            v = json.loads(rec['content'])['match']
        except Exception:
            v = None
        if v:
            with open(store, 'a') as f:
                f.write(json.dumps(dict(key=k, match=v)) + '\n')
    with ThreadPoolExecutor(2) as ex:
        list(ex.map(one, jobs.items()))
    print('judge jobs', len(jobs), t.counts)


def verdicts():
    store = OUT / 'judge' / 'verdicts.jsonl'
    return {json.loads(x)['key']: json.loads(x)['match'] for x in store.read_text().splitlines()} if store.exists() else {}


def prf(pred, g):
    tp = sum(1 for i, p in pred.items() if p and g[i]['label'] == 1)
    fp = sum(1 for i, p in pred.items() if p and g[i]['label'] == 0)
    fn = sum(1 for i, p in pred.items() if not p and g[i]['label'] == 1)
    pr = tp / (tp + fp) if tp + fp else 0
    rc = tp / (tp + fn) if tp + fn else 0
    return dict(tp=tp, fp=fp, fn=fn, P=round(pr, 3), R=round(rc, 3), F1=round(2 * pr * rc / (pr + rc), 3) if pr + rc else 0)


def sign_p(b, w):
    n = b + w
    return round(sum(comb(n, k) for k in range(max(b, w), n + 1)) / 2 ** n * 2, 3) if n else 1.0


def report(name, rep):
    g, recs, V = gold(name), load(name, rep), verdicts()
    ids = [i for i in recs if i in g]
    out = dict(set=name, rep=rep, rows=len(ids), positives=sum(g[i]['label'] for i in ids), arms={})
    preds = {arm: {i: decide(recs[i])[arm] for i in ids} for arm in ARMS}
    for arm in ARMS:
        m = prf(preds[arm], g)
        cause = Counter()
        for i in ids:
            if preds[arm][i] and g[i]['label'] == 1:
                acc = accusation(recs[i], arm)
                if acc['origin'] == 'GUARD':
                    cause['GUARD_MECHANICAL'] += 1
                elif acc['origin'] == 'A_adm2' or not g[i].get('cause'):
                    cause['UNJUDGED'] += 1
                else:
                    cause[V.get(jkey(acc['text'], g[i]['cause']), 'UNJUDGED')] += 1
        gained = sum(1 for i in ids if preds[arm][i] and not preds['A'][i] and g[i]['label'] == 1)
        lost = sum(1 for i in ids if not preds[arm][i] and preds['A'][i] and g[i]['label'] == 1)
        fp_add = sum(1 for i in ids if preds[arm][i] and not preds['A'][i] and g[i]['label'] == 0)
        fp_rem = sum(1 for i in ids if not preds[arm][i] and preds['A'][i] and g[i]['label'] == 0)
        better, worse = gained + fp_rem, lost + fp_add
        pairs = defaultdict(list)
        for i in ids:
            if g[i].get('pair'):
                pairs[g[i]['pair']].append(int(preds[arm][i]) == g[i]['label'])
        full = [all(v) for v in pairs.values() if len(v) == 2]
        out['arms'][arm] = dict(**m, cause=dict(cause), cause_same=cause.get('SAME', 0) + cause.get('GUARD_MECHANICAL', 0),
                                vs_A=dict(tp_gained=gained, tp_lost=lost, fp_added=fp_add, fp_removed=fp_rem, sign_p=sign_p(better, worse)),
                                pair_acc=f'{sum(full)}/{len(full)}' if full else None)
    fam = defaultdict(lambda: defaultdict(int))
    for i in ids:
        if g[i]['label'] == 1:
            fam[g[i]['family']]['n'] += 1
            for arm in ('A', 'B', 'Bv', 'C', 'D'):
                fam[g[i]['family']][arm] += preds[arm][i]
    out['family_recall'] = {k: dict(v) for k, v in sorted(fam.items())}
    cand = defaultdict(Counter)
    for i in ids:
        r = recs[i]
        for k in ('B', 'C'):
            c = (r.get(k) or {}).get('candidate')
            if not c:
                continue
            ver = (r[k].get('verify') or {}).get('verdict')
            if g[i]['label'] == 0:
                cand[k]['false'] += 1
                cand[k]['false_rejected'] += int(ver != 'SUPPORTED')
            else:
                text = (c.get('requirement') or '') + ' — ' + c['reason']
                j = V.get(jkey(text, g[i].get('cause') or ''), 'UNJUDGED')
                cand[k]['true_' + j] += 1
                if j == 'SAME':
                    cand[k]['true_same_kept'] += int(ver == 'SUPPORTED')
                else:
                    cand[k]['true_notsame_kept'] += int(ver == 'SUPPORTED')
        for k in ('B', 'C'):
            v = (r.get(k) or {}).get('verify') or {}
            if v.get('downgraded'):
                cand[k]['downgraded_quote'] += 1
    out['candidates'] = {k: dict(v) for k, v in cand.items()}
    esc = [i for i in ids if recs[i].get('escalated')]
    cost = Counter()
    for i in ids:
        r = recs[i]
        cost['A_calls'] += r['A']['cost']['calls']
        cost['A_tokens'] += r['A']['cost']['prompt_tokens'] + r['A']['cost']['completion_tokens']
        for k, tag in (('B', 'B'), ('C', 'C')):
            x = r.get(k)
            if x:
                cost[tag + '_calls'] += 1
                cost[tag + '_tokens'] += (x.get('usage') or {}).get('total_tokens') or 0
                if x.get('verify'):
                    cost[tag + 'v_calls'] += 1
                    cost[tag + 'v_tokens'] += (x['verify'].get('usage') or {}).get('total_tokens') or 0
        if r.get('Av'):
            cost['Av_calls'] += 1
    out['escalated'] = len(esc)
    out['cost'] = dict(cost)
    out['admissions'] = {k: dict(Counter(str((recs[i].get(k) or {}).get('admission'))[:40] for i in esc)) for k in ('B', 'C')}
    out['A_adm2_changed'] = sum(1 for i in ids if recs[i].get('A_adm2') and (recs[i]['A_adm2']['decision'] or 'NONE') != (next((s.get('decision') for s in recs[i]['A']['steps'] if s.get('tag') == 'review'), None) or 'NONE'))
    path = OUT / 'reports' / f'{name}_rep{rep}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('stage', choices=['judge', 'report'])
    ap.add_argument('--set', required=True)
    ap.add_argument('--rep', type=int, default=1)
    a = ap.parse_args()
    judge(a.set, a.rep) if a.stage == 'judge' else report(a.set, a.rep)
