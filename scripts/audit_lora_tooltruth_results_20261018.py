"""Independent count/ranking audit of v2b Guardian results, without scorer imports."""
import argparse
import csv
import hashlib
import json
from pathlib import Path


def lines(path):
    return [json.loads(line) for line in path.read_bytes().splitlines() if line.strip()]


def csvrows(path):
    with path.open(encoding='utf8', newline='') as f:
        return list(csv.DictReader(f))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--study', type=Path, required=True)
    p.add_argument('--old', type=Path, required=True)
    p.add_argument('--protected', type=Path, required=True)
    p.add_argument('--saved', type=Path, required=True)
    a = p.parse_args()
    csv.field_size_limit(2**31 - 1)
    study = a.study
    result = json.loads((study / 'ANALYSIS.json').read_bytes())
    requests = lines(study / 'run/requests.jsonl')
    scores = lines(study / 'run/scores.jsonl')
    assert len(requests) == 1272 and len(scores) == 815
    # Request records retain source pairs and rendered input hashes; their schema
    # is checked below without reconstructing a model prompt through its scorer.
    new = {r['id']: r for r in scores if r['partition'] == 'regression_seen'}
    old = {(r['arm'], r['id']): r for r in lines(a.old / 'transfer/scores.jsonl')
           if r['dataset'] == 'regression_seen'}
    inputs = csvrows(a.protected / 'regression_seen/inputs.csv')
    gold = lines(a.protected / 'regression_seen/labels.jsonl')
    saved = csvrows(a.saved / 'regression_r1/rows.csv')
    assert [r['id'] for r in inputs] == [r['id'] for r in gold] == [r['id'] for r in saved]
    valid = {r['id'] for r in csvrows(a.saved / 'valid46_r1/rows.csv')}
    pools = dict(seen397=list(range(397)),
                 real191=[i for i, g in enumerate(gold) if g['domain'] in ('ext_tau2', 'hold_tau2h', 'hold_holdout2')],
                 valid46=[i for i, r in enumerate(inputs) if r['id'] in valid])
    checks = 0
    for name, ix in pools.items():
        y = [gold[i]['label'] for i in ix]
        hard = {j for j, i in enumerate(ix) if saved[i]['hard'] != ''}
        arms = {k: [] for k in ('qwen4b_base', 'qwen4b_v1', 'qwen4b_v2', 'qwen35b_current_max')}
        for i in ix:
            identity = inputs[i]['id']
            sourcehash = hashlib.sha256((inputs[i]['prompt'] + '\0' + inputs[i]['response']).encode('utf8', 'surrogatepass')).hexdigest()
            assert new[identity]['row_sha256'] == sourcehash
            assert new[identity]['input_sha256'] == old['base', identity]['input_sha256'] == old['adapter', identity]['input_sha256']
            arms['qwen4b_base'].append(old['base', identity]['score'])
            arms['qwen4b_v1'].append(old['adapter', identity]['score'])
            arms['qwen4b_v2'].append(new[identity]['score'])
            arms['qwen35b_current_max'].append(float(saved[i]['score']))
        for arm, ss in arms.items():
            ref = result['datasets'][name]['arms'][arm]
            # Pairwise Mann-Whitney AUC, independently of sklearn's ROC routine.
            positives = [s for t, s in zip(y, ss) if t]
            negatives = [s for t, s in zip(y, ss) if not t]
            auc = sum((x > z) + .5 * (x == z) for x in positives for z in negatives) / (len(positives) * len(negatives))
            assert abs(auc - ref['ranking']['roc_auc']) < 1e-12
            for q in (.3, .4, .5, .6):
                selected = set(hard)
                for j in sorted(range(len(ix)), key=lambda j: (-ss[j], j)):
                    if len(selected) >= round(q * len(ix)):
                        break
                    selected.add(j)
                tp = sum(y[j] for j in selected)
                fp = len(selected) - tp
                fn = sum(y) - tp
                tn = len(y) - tp - fp - fn
                m = ref['quotas'][str(q)]
                assert (tp, fp, fn, tn) == (m['tp'], m['fp'], m['fn'], m['tn'])
                assert abs(2 * tp / (2 * tp + fp + fn) - m['f1']) < 1e-12
                checks += 1
    out = dict(complete=True, raw_requests=1272, scores=815, source_hashes_checked=397,
               quota_tables_checked=checks, auc_pairs_checked=12,
               method='stdlib counts and pairwise Mann-Whitney AUC; no scorer or sklearn imports',
               scope='Arithmetic and identity checks, not independent policy annotation')
    (study / 'RESULTS_CPU_AUDIT.json').write_bytes((json.dumps(out, indent=2) + '\n').encode())
    print(json.dumps(out))


if __name__ == '__main__':
    main()
