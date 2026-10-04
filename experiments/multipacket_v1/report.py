"""Metrics, reason judging and per-case change tables for multipacket runs.

    python -m experiments.multipacket_v1.report --suite valid46 --runs 1 [--judge]"""
import argparse, json
from collections import Counter
from math import comb
from experiments.evidence_packer_v2.llm_eval import JUDGE_MODEL, JUDGE_PROMPT
from experiments.multipacket_v1.common import OUT, references, valid_gold
from experiments.multipacket_v1.llm import call


def gold_of(suite):
    if suite == 'valid46':
        return valid_gold()
    return json.loads((OUT / 'suite_syn_m1/GOLD_eval_only.json').read_text())


def load(suite, run, arm):
    f = OUT / 'runs' / suite / f'run{run}' / f'{arm}.jsonl'
    return {json.loads(l)['id']: json.loads(l) for l in open(f)} if f.exists() else {}


def final_reply(rec):
    dec = [s for s in rec.get('steps', []) if (s.get('admitted') or {}).get('decision') is not None]
    match = [s for s in dec if s['admitted']['decision'] == rec['decision']]
    return (match[-1] if match else (dec[-1] if dec else {})).get('admitted')


def judge(rec, g):
    a = final_reply(rec)
    if not a or rec['decision'] != 'ERROR' or g['label'] != 1 or not g.get('explanation'):
        return None
    msg = json.dumps(dict(gold_explanation=g['explanation'], verifier=dict(regulated_action=a['regulated_action'],
                          applicable_norms=a['applicable_norms'], reason=a['reason'])), ensure_ascii=False)
    req = dict(model=JUDGE_MODEL, temperature=0, max_tokens=1500, response_format=dict(type='json_object'),
               messages=[dict(role='system', content=JUDGE_PROMPT), dict(role='user', content=msg)])
    r = call(req, provider='ollama', tag='judge')
    try:
        return json.loads(r['content'])['match']
    except Exception:
        return 'JUDGE_FAILED'


def metrics(recs, gold, ids, judged, field='decision'):
    c = Counter(); calls = tin = tout = 0; reason = Counter()
    for i in ids:
        r = recs.get(i); y = gold[i]['label']
        if r is None or r.get('decision') is None:
            c['tech'] += 1; pred = 0
        else:
            d = r.get(field) or r['decision']; c['unknown'] += d == 'UNKNOWN'; pred = int(d == 'ERROR')
            for s in r['steps']:
                if s.get('key', '').startswith('u2cache') and r['arm'] not in ('A', 'B', 'FULL', 'CTRL'):
                    continue          # shared first pass counted once per row in A
                calls += 1
                u = s.get('usage') or {}; tin += u.get('prompt_tokens', 0); tout += u.get('completion_tokens', 0)
        c['tp'] += pred and y; c['fp'] += pred and not y; c['fn'] += (not pred) and y; c['tn'] += (not pred) and not y
        if pred and y and field == 'decision':
            reason[judged.get(i)] += 1
    p = c['tp'] / (c['tp'] + c['fp']) if c['tp'] + c['fp'] else 0; rc = c['tp'] / (c['tp'] + c['fn']) if c['tp'] + c['fn'] else 0
    return dict(**c, precision=round(p, 3), recall=round(rc, 3), f1=round(2 * p * rc / (p + rc), 3) if p + rc else 0,
                acc=round((c['tp'] + c['tn']) / len(ids), 3), reason_same=reason['SAME'], reason_partial=reason['PARTIAL'],
                reason_diff=reason['DIFFERENT'], reason_correct_tp=reason['SAME'] + reason['PARTIAL'],
                extra_calls_per_row=round(calls / len(ids), 2), prompt_tokens_per_row=round(tin / len(ids)), completion_tokens_per_row=round(tout / len(ids)))


def sign_p(w, l):
    n = w + l
    return min(1.0, 2 * sum(comb(n, k) for k in range(max(w, l), n + 1)) / 2 ** n) if n else 1.0


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--suite', default='valid46'); ap.add_argument('--runs', default='1')
    ap.add_argument('--arms', default=None); ap.add_argument('--judge', action='store_true'); ap.add_argument('--tag', default='')
    a = ap.parse_args()
    gold = gold_of(a.suite); refs = references() if a.suite == 'valid46' else {}
    runs = [int(x) for x in a.runs.split(',')]
    arm_names = a.arms.split(',') if a.arms else sorted({f.stem for r in runs for f in (OUT / 'runs' / a.suite / f'run{r}').glob('*.jsonl')})
    if 'A' not in arm_names:
        arm_names = ['A'] + arm_names
    subsets = {'all': list(gold)}
    if a.suite == 'valid46':
        subsets.update(ref15=[i for i in gold if i in refs], unseen31=[i for i in gold if i not in refs])
    report, cases = {}, []
    for run in runs:
        base = load(a.suite, run, 'A')
        for arm in arm_names:
            recs = load(a.suite, run, arm)
            if arm == 'A' and not recs and a.suite == 'valid46':
                from experiments.multipacket_v1.common import baseline_reply
                recs = {i: dict(id=i, arm='A', decision=(baseline_reply('U2_20k', i, run)['admitted'] or {}).get('decision'),
                                steps=[dict(key='u2cache', admitted=baseline_reply('U2_20k', i, run)['admitted'], usage=baseline_reply('U2_20k', i, run)['usage'])])
                        for i in gold}
                base = recs
            for n, other in (('B', 'U2_48k'), ('FULL', 'FULL')):
                if arm == n and not recs and a.suite == 'valid46':
                    from experiments.multipacket_v1.common import baseline_reply
                    recs = {i: dict(id=i, arm=n, decision=(baseline_reply(other, i, run)['admitted'] or {}).get('decision'),
                                    steps=[dict(key='u2cache', admitted=baseline_reply(other, i, run)['admitted'], usage=baseline_reply(other, i, run)['usage'])])
                            for i in gold if baseline_reply(other, i, run)}
            if not recs:
                continue
            judged = {i: judge(r, gold[i]) for i, r in recs.items()} if a.judge else {}
            for s, ids in subsets.items():
                ids = [i for i in ids if arm not in ('ORACLE_E', 'ORACLE_R') or i in refs]
                if not ids:
                    continue
                report[f'{arm}|{s}|run{run}'] = metrics(recs, gold, ids, judged)
                for alt in ('sticky', 'any_error'):
                    if any(alt in r for r in recs.values()):
                        report[f'{arm}[{alt}]|{s}|run{run}'] = metrics(recs, gold, ids, {}, field=alt)
            if arm != 'A' and base:
                w = l = 0
                for i, r in recs.items():
                    b = base.get(i, {}).get('decision'); d = r.get('decision'); y = gold[i]['label']
                    if b != d:
                        good = int(d == 'ERROR') == y; bad = int(b == 'ERROR') == y
                        w += good and not bad; l += bad and not good
                        cases.append(dict(run=run, arm=arm, id=i, gold=y, base=b, new=d, fixed=good and not bad, broke=bad and not good,
                                          judge=judged.get(i), base_reason=(final_reply(base.get(i, {})) or {}).get('reason'),
                                          new_reason=(final_reply(r) or {}).get('reason'),
                                          info={k: r.get(k) for k in ('degenerate', 'flagged', 'controller', 'qa_rounds', 'answered', 'established', 'new_units') if k in r}))
                report[f'{arm}|vs_A|run{run}'] = dict(fixed=w, broke=l, sign_p=round(sign_p(w, l), 3))
    out = OUT / 'reports'; out.mkdir(parents=True, exist_ok=True)
    stem = f'{a.suite}_runs{"-".join(map(str, runs))}{a.tag}'
    (out / f'{stem}.json').write_text(json.dumps(report, indent=1))
    (out / f'{stem}_changes.jsonl').write_text('\n'.join(json.dumps(c, ensure_ascii=False) for c in cases))
    for k, v in report.items():
        if '|all|' in k or 'vs_A' in k:
            print(k, {x: v[x] for x in v if x in ('tp', 'fp', 'fn', 'f1', 'unknown', 'tech', 'reason_correct_tp', 'reason_diff', 'extra_calls_per_row', 'prompt_tokens_per_row', 'fixed', 'broke', 'sign_p')})


if __name__ == '__main__':
    main()
