"""Amendment 2: rescore the stored commit-5 ext_tau2 records on gold v2 (no Guardian/V4 calls). The frozen scorer
(experiments/verification_v4/score.py) is reused unchanged; only the verdict lookup is extended so that an accusation is
cause-correct if the unchanged judge says SAME for ANY acceptable cause of the row.
  python -m experiments.verification_v4.external.rescore_v2 judge|report --set ext_tau2v2[_strict] --reps 1,2,3"""
import argparse, json, shutil
from concurrent.futures import ThreadPoolExecutor

from experiments.verification_v4 import score as S
from guardian_truth.integrated import Transport
from guardian_truth.verification.v4 import decide_v4


def link_runs(name):
    d = S.OUT / 'runs' / name
    d.mkdir(parents=True, exist_ok=True)
    for rep in (1, 2, 3):
        src = S.OUT / 'runs' / 'ext_tau2' / f'rep{rep}_v4.jsonl'
        if not (d / src.name).exists():
            shutil.copyfile(src, d / src.name)


def texts(rec):
    t = [acc['text'] for p, acc in decide_v4(rec).values() if p and acc['origin'] != 'GUARD' and acc['text']]
    return sorted(set(t + [S.ctext(c) for _, c, _ in S.cands(rec)]))


def judge(name, reps):
    g = S.gold(name)
    t = Transport('mistral', S.JUDGE_MODEL, S.OUT / 'cache' / 'judge', max_calls=1500, retry_failed=3, sender=S.paced)
    store = S.OUT / 'judge' / 'verdicts.jsonl'
    done = set(S.verdicts())
    jobs = {}
    for rep in reps:
        for i, rec in S.load(name, rep, '_v4').items():
            if i in g and g[i]['label'] == 1 and 'error' not in rec:
                for x in texts(rec):
                    for c in g[i]['causes']:
                        k = S.jkey(x, c)
                        if k not in done:
                            jobs[k] = (x, c)

    def one(item):
        k, (text, cause) = item
        msg = json.dumps(dict(gold_explanation=cause, verifier=dict(reason=text)), ensure_ascii=False)
        req = dict(model=S.JUDGE_MODEL, temperature=0, max_tokens=600, response_format=dict(type='json_object'),
                   messages=[dict(role='system', content=S.JUDGE_PROMPT), dict(role='user', content=msg)])
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


def any_cause_verdicts(name, reps):
    g, V = S.gold(name), S.verdicts()
    V2 = dict(V)
    for rep in reps:
        for i, rec in S.load(name, rep, '_v4').items():
            if i in g and g[i]['label'] == 1:
                for x in texts(rec):
                    vs = [V.get(S.jkey(x, c)) for c in g[i]['causes']]
                    V2[S.jkey(x, g[i]['cause'])] = 'SAME' if 'SAME' in vs else ('DIFFERENT' if any(vs) else None)
    return V2


def report(name, reps):
    V2 = any_cause_verdicts(name, reps)
    S.verdicts = lambda: V2
    g = S.gold(name)
    summary = {}
    for rep in reps:
        print(f'===== {name} rep {rep}')
        out = S.report(name, rep, '_v4', quiet=True)
        recs = S.load(name, rep, '_v4')
        ids = [i for i in recs if i in g]
        dec = {i: decide_v4(recs[i]) for i in ids}
        sub = {'all': ids, 'format_only': [i for i in ids if g[i]['label'] == 0 or g[i]['format_only']],
               'substantive': [i for i in ids if g[i]['label'] == 0 or not g[i]['format_only']]}
        rs = {}
        for sn, sids in sub.items():
            for arm in ('A', 'A_DF', 'A_Ems', 'A_AT', 'A_CTRL', 'V4', 'V4_mechanical', 'V4_mech_strict'):
                pred = {i: dec[i][arm][0] for i in sids}
                m = S.prf(pred, g)
                gain = [i for i in sids if pred[i] and not dec[i]['A'][0] and g[i]['label'] == 1]
                nfp = [i for i in sids if pred[i] and not dec[i]['A'][0] and g[i]['label'] == 0]
                lost = [i for i in sids if not pred[i] and dec[i]['A'][0]]
                row = dict(tp=m['tp'], fp=m['fp'], F1=round(m['F1'], 3), new_tp=len(gain), new_fp=len(nfp), lost=len(lost))
                if sn == 'all':
                    a = out['strata']['all'][arm]
                    row.update(cc=a['cause_correct_tp'], new_cc=a['gain_cause_correct'], later=a['later_call_recall'],
                               gain_ids=a['gain_ids'], fp_ids=a['fp_ids'])
                    mm = out['strata']['multi'][arm]
                    row.update(multi_new_cc=mm['gain_cause_correct'], multi_new_fp=mm['new_fp'], multi_new_tp=mm['gain'])
                rs.setdefault(sn, {})[arm] = row
                print(f"  {sn:11s} {arm:14s} tp={m['tp']:2d} fp={m['fp']:2d} F1={m['F1']:.3f} newTP={len(gain)} newFP={len(nfp)}"
                      + (f" cc={row['cc']} newcc={row['new_cc']} later={row['later']} multi(newTP/cc/FP)={row['multi_new_tp']}/{row['multi_new_cc']}/{row['multi_new_fp']} {row['gain_ids']} FP{row['fp_ids']}" if sn == 'all' else ''))
        summary[rep] = rs
    p = S.OUT.parent / 'verification_v4' / 'external' / name / 'RESCORE_v2.json'
    p.write_text(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('stage', choices=['judge', 'report'])
    ap.add_argument('--set', required=True)
    ap.add_argument('--reps', default='1,2,3')
    a = ap.parse_args()
    reps = [int(x) for x in a.reps.split(',')]
    link_runs(a.set)
    judge(a.set, reps) if a.stage == 'judge' else report(a.set, reps)
