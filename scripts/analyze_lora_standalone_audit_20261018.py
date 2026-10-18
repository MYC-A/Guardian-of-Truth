"""Compare separate-process audit receipts and recompute all valid46 decisions."""
import argparse
import csv
import json
import math
from pathlib import Path

from audit_lora_results_cpu_20261018 import read, table, quota
from sklearn.metrics import (confusion_matrix, f1_score, precision_score,
                             recall_score, roc_auc_score, average_precision_score)


def metrics(y, prediction):
    tn, fp, fn, tp = map(int, confusion_matrix(y, prediction, labels=[0, 1]).ravel())
    return dict(tp=tp, fp=fp, fn=fn, tn=tn,
                f1=float(f1_score(y, prediction, zero_division=0)),
                precision=float(precision_score(y, prediction, zero_division=0)),
                recall=float(recall_score(y, prediction, zero_division=0)))


def difference(left, right):
    assert left.keys() == right.keys()
    for key in left:
        for field in ('input_sha256', 'input_token_sha256', 'row_sha256'):
            assert left[key][field] == right[key][field], (key, field)
    delta = [abs(left[k]['score'] - right[k]['score']) for k in left]
    return dict(rows=len(delta), exact_equal=sum(d == 0 for d in delta),
                max_abs_difference=max(delta), all_exact=all(d == 0 for d in delta))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--study', type=Path, required=True)
    p.add_argument('--audit', type=Path, required=True)
    p.add_argument('--saved', type=Path, required=True)
    p.add_argument('--pin', type=Path, required=True)
    a = p.parse_args()
    csv.field_size_limit(2**31 - 1)
    selection = json.loads((a.study / 'BASELINE_AUDIT_SELECTION.json').read_bytes())['rows']
    selected = {(r['dataset'], r['id']) for r in selection}
    assert len(selected) == 78
    original = {}
    for r in read(a.study / 'run/scores.jsonl') + read(a.study / 'transfer/scores.jsonl'):
        name = r.get('dataset', r.get('partition'))
        if (name, r['id']) in selected:
            original[r['arm'], name, r['id']] = r
    arms = {}
    done = {}
    pin = json.loads(a.pin.read_bytes())
    hashes = {r['path']: r['digest'] for r in pin['files'] if r['path'].endswith('.safetensors')}
    for mode in ('vanilla', 'disabled', 'active'):
        folder = a.audit / ('lora-audit-' + mode)
        done[mode] = json.loads((folder / 'DONE.json').read_bytes())
        assert done[mode]['complete'] and done[mode]['rows'] == 78
        assert done[mode]['base_weights_sha256'] == hashes
        assert done[mode]['training_steps_added'] == 0
        rows = read(folder / 'scores.jsonl')
        arms[mode] = {(r['dataset'], r['id']): r for r in rows}
        assert len(rows) == len(arms[mode]) == 78 and arms[mode].keys() == selected
        assert all(math.isfinite(r['score']) and abs(r['score']-r['log_softmax_score']) < 1e-4 for r in rows)
    checks = {'vanilla_vs_disabled': difference(arms['vanilla'], arms['disabled'])}
    for mode, old_arm in [('vanilla', 'base'), ('disabled', 'base'), ('active', 'adapter')]:
        old = {key: original[old_arm, *key] for key in selected}
        checks[mode + '_vs_original_' + old_arm] = difference(arms[mode], old)
    valid = table(a.saved / 'valid46_r1/rows.csv')
    y = [int(r['label']) for r in valid]
    hard = {i for i, r in enumerate(valid) if r['hard']}
    output = {}
    predictions = {}
    for mode in arms:
        scores = [arms[mode]['regression_seen', r['id']]['score'] for r in valid]
        predictions[mode] = quota(scores, .4, hard)
        output[mode] = dict(
            quotas={str(q): metrics(y, quota(scores, q, hard)) for q in (.3, .4, .5, .6)},
            zero=metrics(y, [int(s > 0 or i in hard) for i, s in enumerate(scores)]),
            ranking=dict(roc_auc=float(roc_auc_score(y, scores)),
                         average_precision=float(average_precision_score(y, scores))))
    b, l = predictions['vanilla'], predictions['active']
    changes = [dict(id=r['id'], label=y[i], before=b[i], after=l[i],
                    base_score=arms['vanilla']['regression_seen', r['id']]['score'],
                    adapter_score=arms['active']['regression_seen', r['id']]['score'])
               for i, r in enumerate(valid) if b[i] != l[i]]
    result = dict(schema='lora-standalone-audit-analysis-v1', complete=True,
                  numerical_checks=checks, all_scores_exactly_reproduced=all(c['all_exact'] for c in checks.values()),
                  valid46=dict(rows=46, positives=sum(y), hard=len(hard), arms=output,
                               changes_at40=changes), process_receipts=done,
                  limitations=['All valid46 rows audited; only16 dev and16 external rows independently rerun',
                               'Does not independently adjudicate semantic gold or prove generalization'])
    (a.audit / 'ANALYSIS.json').write_bytes((json.dumps(result, indent=2)+'\n').encode())
    print(json.dumps({k:v for k,v in result.items() if k != 'process_receipts'}, indent=2))


if __name__ == '__main__':
    main()
