"""Aggregate repeated runs of the same frozen requests: per-run F1 (mean/min/max), majority-vote F1,
and reviewer noise (decision flips across runs on byte-identical requests). Technical nulls -> 0, as in report."""
import json, sys
from pathlib import Path
from statistics import mean

from experiments.evidence_packer_v2.llm_eval import ARMS, ROOT, rows


def f1(pred, gold, ids):
    tp = sum(pred[i] and gold[i] for i in ids); fp = sum(pred[i] and not gold[i] for i in ids)
    fn = sum((not pred[i]) and gold[i] for i in ids)
    return 2 * tp / (2 * tp + fp + fn) if tp else 0.0


def main(dirs):
    dirs = [Path(d) for d in dirs]
    gold = {r['id']: r['label'] for r in rows()}
    refs = json.loads((ROOT / 'experiments/retrieval_bakeoff_v1/fixtures/references.json').read_text())
    subsets = {'all46': list(gold), 'ref15': [i for i in gold if i in refs], 'unseen31': [i for i in gold if i not in refs]}
    man = json.loads((dirs[0] / 'manifest.json').read_text())['entries']
    dec = {}
    for k, d in enumerate(dirs):
        for key, v in man.items():
            p = d / 'replies' / v['file'].split('requests/')[1]
            a = json.loads(p.read_text()).get('admitted') if p.exists() else None
            dec[(k, key)] = a['decision'] if a else 'NULL'
    out = {}
    for arm in ARMS:
        runs = [{i: int(dec[(k, f'{arm}/{i}')] == 'ERROR') for i in gold} for k in range(len(dirs))]
        vote = {i: int(sum(r[i] for r in runs) * 2 > len(runs)) for i in gold}
        flips = sum(len({dec[(k, f'{arm}/{i}')] for k in range(len(dirs))}) > 1 for i in gold)
        out[arm] = {s: dict(f1_runs=[round(f1(r, gold, ids), 3) for r in runs],
                            f1_mean=round(mean(f1(r, gold, ids) for r in runs), 3),
                            f1_majority=round(f1(vote, gold, ids), 3)) for s, ids in subsets.items()}
        out[arm]['rows_with_flip_across_runs'] = flips
    print(json.dumps(out, indent=1))
    (dirs[0] / 'report_repeats.json').write_text(json.dumps(out, indent=1))


if __name__ == '__main__':
    main(sys.argv[1:])
