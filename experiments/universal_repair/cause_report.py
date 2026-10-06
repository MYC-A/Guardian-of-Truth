"""Cause report: joins every positive prediction (arm/set/rep) with its source-seeing judgement (dedup key: set,id,accusation).
Writes outputs/universal_repair/cause/cause_report.{json,md}; judge variance = a0 vs a1 category agreement on the re-judged subset."""
import json
from collections import Counter, defaultdict

from guardian_truth.repair.cause import CORRECT
from guardian_truth.repair.v5 import decide
from .run import OUT
from .score import gold_for, arm_records

SETS = ['valid46:1', 'valid46:2', 'valid46:3', 'lb_long:1', 'lb2_long:1', 'lb3_long:1', 'lb3_long:2', 'ext_tau2:1', 'ext_tau2:2',
        'ext_tau2:3', 'hold_tau2h:1', 'hold_tau2h:2', 'hold_tau2h:3']
ARMS = ['V4r', 'R_fix', 'R_comb']


def load(a):
    p = OUT / 'cause' / f'judgements_a{a}.jsonl'
    d = {}
    if p.exists():
        for l in p.read_text(encoding='utf-8').splitlines():
            r = json.loads(l)
            d[(r['set'], r['id'], r['acc_text'])] = r['judgement']
    return d


def main():
    J0, J1 = load(0), load(1)
    out, lines = {}, ['| set#rep | arm | TP (label) | TP correct cause | TP alt. supported | TP unsupported/unresolved | FP | FP alt. supported (gold?) | unjudged |',
                      '|---|---|---|---|---|---|---|---|---|']
    tot = defaultdict(Counter)
    for sr in SETS:
        s, rep = sr.split(':'); rep = int(rep); g = gold_for(s)
        for arm in ARMS:
            recs = None
            for mode in (['offline', 'live'] if arm == 'V4r' else ['live']):
                try:
                    recs, _ = arm_records(s, rep, arm, mode); break
                except FileNotFoundError:
                    continue
            if recs is None:
                continue
            c = Counter(); rows = []
            for i, r in recs.items():
                if i not in g:
                    continue
                p, acc = decide(r)
                if not p:
                    continue
                j = J0.get((s, i, (acc or {}).get('text') or ''))
                cat = (j or {}).get('category', 'not_judged')
                lab = g[i]['label']
                c['tp' if lab else 'fp'] += 1
                if cat in ('not_judged', 'technical_unjudged'):
                    c['unjudged'] += 1
                elif lab and cat in CORRECT:
                    c['tp_correct'] += 1
                elif lab and cat in ('alternative_supported_cause', 'gold_conflict'):
                    c['tp_alt'] += 1
                elif lab:
                    c['tp_bad'] += 1
                elif cat in ('alternative_supported_cause', 'gold_conflict', 'supported_correct_core', 'supported_core_with_unsupported_extra'):
                    c['fp_alt'] += 1
                rows.append(dict(id=i, label=lab, origin=(acc or {}).get('origin'), category=cat))
            out[f'{sr}:{arm}'] = dict(counts=dict(c), rows=rows)
            tot[arm].update(c)
            lines.append(f"| {s}#{rep} | {arm} | {c['tp']} | {c['tp_correct']} | {c['tp_alt']} | {c['tp_bad']} | {c['fp']} | {c['fp_alt']} | {c['unjudged']} |")
    for arm, c in tot.items():
        lines.append(f"| **all** | {arm} | {c['tp']} | {c['tp_correct']} | {c['tp_alt']} | {c['tp_bad']} | {c['fp']} | {c['fp_alt']} | {c['unjudged']} |")
    out['_total'] = {a: dict(c) for a, c in tot.items()}
    both = [k for k in J1 if k in J0]
    agree = sum(J0[k].get('category') == J1[k].get('category') for k in both)
    corr = sum((J0[k].get('category') in CORRECT) == (J1[k].get('category') in CORRECT) for k in both)
    out['_judge_variance'] = dict(n=len(both), category_agree=agree, correct_vs_not_agree=corr)
    lines.append(f"\nJudge variance (a0 vs a1 re-judgement): n={len(both)}, same category {agree}, same correct/not-correct {corr}.")
    (OUT / 'cause' / 'cause_report.json').write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    (OUT / 'cause' / 'cause_report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
