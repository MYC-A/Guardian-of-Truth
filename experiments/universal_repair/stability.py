"""P4 stability: per arm/set, metric range over reps and row-level flips (prediction differs between reps).
Judge variance is reported separately (cause/judge_variance.json)."""
import json
import sys
from pathlib import Path

REP = Path(sys.argv[1] if len(sys.argv) > 1 else 'outputs/universal_repair/phase4/report.json')


def main():
    r = json.loads(REP.read_text(encoding='utf-8'))
    by = {}
    for sr, arms in r['sets'].items():
        s, rep = sr.split('#')
        for arm, m in arms.items():
            if 'missing' in m:
                continue
            by.setdefault((s, arm), {})[int(rep)] = m
    out, lines = {}, ['| set | arm | reps | TP | FP | FN | F1 | flipped rows (any rep differs) | flipped ERR / OK |', '|---|---|---|---|---|---|---|---|---|']
    for (s, arm), reps in sorted(by.items()):
        if len(reps) < 2:
            continue
        rng = {k: (min(m[k] for m in reps.values()), max(m[k] for m in reps.values())) for k in ('tp', 'fp', 'fn', 'f1')}
        ids = set.intersection(*(set(m['pred']) for m in reps.values()))
        flips = sorted(i for i in ids if len({m['pred'][i][0] for m in reps.values()}) > 1)
        out[f'{s}:{arm}'] = dict(reps=sorted(reps), range=rng, flips=flips)
        f = lambda k: f'{rng[k][0]}–{rng[k][1]}' if rng[k][0] != rng[k][1] else f'{rng[k][0]}'
        lines.append(f"| {s} | {arm} | {len(reps)} | {f('tp')} | {f('fp')} | {f('fn')} | {f('f1')} | {len(flips)} | |")
    p = REP.parent / 'stability.json'
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    (REP.parent / 'stability.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
