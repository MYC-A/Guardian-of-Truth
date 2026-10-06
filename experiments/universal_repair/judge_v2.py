"""Cause judge v2 (docs/universal_repair_v2/JUDGE_V2.md): full packet + coverage + declarations, valid46 explanations as
gold causes, cross-field invariants. Separate cache/ledger: outputs/universal_repair_v2/cache/judge.
  python -X utf8 -m experiments.universal_repair.judge_v2 run --arms V4r,R_fix [--attempt 0] [--dry]
  python -X utf8 -m experiments.universal_repair.judge_v2 recheck_v1      # invariants over stored v1 judgements (no calls)
  python -X utf8 -m experiments.universal_repair.judge_v2 report"""
import argparse, json, threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

from guardian_truth.integrated import Transport
from guardian_truth.repair.cause import CORRECT, gold_causes, invariant, judge_v2
from guardian_truth.repair.clients import ReadThrough
from guardian_truth.repair.v5 import decide
from .run import OUT, MODEL, inputs, paced
from .score import gold_for, arm_records
from .cause_report import SETS

V2 = OUT.parent / 'universal_repair_v2'


def records_for(s, rep, arm):
    for mode in (['offline', 'live'] if arm == 'V4r' else ['live']):
        try:
            return arm_records(s, rep, arm, mode)[0]
        except FileNotFoundError:
            continue
    return None


def positives(arms):
    for sr in SETS:
        s, rep = sr.split(':'); rep = int(rep); g = gold_for(s)
        for arm in arms:
            recs = records_for(s, rep, arm)
            if recs is None:
                continue
            for i, rec in recs.items():
                if i not in g:
                    continue
                p, acc = decide(rec)
                if p:
                    yield s, rep, arm, i, acc or {}, g[i]


def load(path):
    d = {}
    if path.exists():
        for l in path.read_text(encoding='utf-8').splitlines():
            r = json.loads(l); d[(r['set'], r['id'], r['acc_text'])] = r
    return d


def run(a):
    outp = V2 / 'cause' / f'judgements_v2_a{a.attempt}.jsonl'; outp.parent.mkdir(parents=True, exist_ok=True)
    done = {k for k, r in load(outp).items() if r['judgement'].get('category') != 'technical_unjudged'}
    rows = {s: {r['id']: r for r in inputs(s)} for s in {x.split(':')[0] for x in SETS}}
    todo, seen = [], set()
    for s, rep, arm, i, acc, gi in positives(a.arms.split(',')):
        k = (s, i, acc.get('text') or '')
        if k in done or k in seen:
            continue
        seen.add(k); todo.append((s, rep, arm, i, acc, gi, k[2]))
    if a.ids:
        todo = [t for t in todo if t[3] in a.ids.split(',')]
    if a.sample:
        import random
        todo = random.Random(20261006).sample(todo, min(a.sample, len(todo)))
    if a.limit:
        todo = todo[:a.limit]
    print('todo', len(todo), Counter(t[0] for t in todo))
    if a.dry:
        return
    live = Transport('mistral', MODEL, V2 / 'cache' / 'judge', max_calls=a.max_calls, retry_failed=2, sender=paced)
    client = ReadThrough('mistral', MODEL, [], live=live)
    lock = threading.Lock()

    def one(t):
        s, rep, arm, i, acc, gi, text = t
        j = judge_v2(client, MODEL, rows[s][i], acc, gold_causes(gi), attempt=a.attempt)
        with lock, open(outp, 'a', encoding='utf-8', newline='\n') as f:
            f.write(json.dumps(dict(set=s, rep=rep, arm=arm, id=i, label=gi['label'], origin=acc.get('origin'),
                                    acc_text=text, n_gold=len(gold_causes(gi)), judgement=j), ensure_ascii=False) + '\n')
    with ThreadPoolExecutor(2) as ex:
        list(ex.map(one, todo))
    print('judged', len(todo), live.counts)


def recheck_v1(a):
    """Invariants over the stored v1 judgements; valid46 v1 judgements had no gold cause (explanation dropped) -> invalid."""
    J = load(OUT / 'cause' / 'judgements_a0.jsonl')
    c, ex = Counter(), []
    for k, r in J.items():
        j = r['judgement']
        if j.get('category') == 'technical_unjudged':
            c['technical'] += 1; continue
        gi = gold_for(r['set'])[r['id']]
        bad = invariant(j, bool(gold_causes(gi)) and r['set'] != 'valid46')     # v1 saw no valid46 cause
        if r['set'] == 'valid46' and r['label'] == 1:
            c['valid46_tp_judged_without_gold'] += 1
        if bad:
            c['inconsistent'] += 1; c[bad.split(':')[0]] += 1
            ex.append(dict(set=r['set'], id=r['id'], arm=r['arm'], category=j.get('category'), why=bad,
                           fields={f: j.get(f) for f in ('accusation_supported', 'core_matches_gold', 'unsupported_extra', 'gold_supported')}))
    out = dict(n=len(J), counts=dict(c), inconsistent=ex)
    (V2 / 'cause').mkdir(parents=True, exist_ok=True)
    (V2 / 'cause' / 'v1_invariant_recheck.json').write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    print(dict(n=len(J), **c))


def classify(j, label):
    cat = j.get('category')
    if cat in ('technical_unjudged', 'inconsistent_unjudged', None):
        return cat or 'not_judged'
    return cat


def report(a):
    J0, J1 = load(V2 / 'cause' / 'judgements_v2_a0.jsonl'), load(V2 / 'cause' / 'judgements_v2_a1.jsonl')
    tot, per = defaultdict(Counter), {}
    for s, rep, arm, i, acc, gi in positives(a.arms.split(',')):
        r = J0.get((s, i, acc.get('text') or ''))
        j = (r or {}).get('judgement') or {}
        cat = classify(j, gi['label']) if r else 'not_judged'
        c = per.setdefault(f'{s}:{rep}:{arm}', Counter())
        lab = 'tp' if gi['label'] else 'fp'
        for cc in (c, tot[arm]):
            cc[lab] += 1
            cc[f'{lab}:{cat}'] += 1
            if cat not in ('not_judged', 'technical_unjudged', 'inconsistent_unjudged'):
                cc[f'{lab}:source_supported'] += j.get('accusation_supported') == 'yes'
                cc[f'{lab}:gold_match'] += j.get('accusation_supported') == 'yes' and j.get('core_matches_gold') == 'yes'
    both = [k for k in J1 if k in J0]
    var = dict(n=len(both), same_category=sum(J0[k]['judgement'].get('category') == J1[k]['judgement'].get('category') for k in both),
               same_correct=sum((J0[k]['judgement'].get('category') in CORRECT) == (J1[k]['judgement'].get('category') in CORRECT) for k in both))
    out = dict(total={k: dict(v) for k, v in tot.items()}, per={k: dict(v) for k, v in per.items()}, variance=var)
    (V2 / 'cause' / 'cause_report_v2.json').write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(out['total'], indent=1)); print(var)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['run', 'recheck_v1', 'report'])
    ap.add_argument('--arms', default='V4r,R_fix'); ap.add_argument('--attempt', type=int, default=0)
    ap.add_argument('--limit', type=int, default=0); ap.add_argument('--max-calls', type=int, default=700)
    ap.add_argument('--ids'); ap.add_argument('--dry', action='store_true')
    ap.add_argument('--sample', type=int, default=0, help='seeded random subset (variance re-judgement)')
    a = ap.parse_args()
    dict(run=run, recheck_v1=recheck_v1, report=report)[a.cmd](a)


if __name__ == '__main__':
    main()
