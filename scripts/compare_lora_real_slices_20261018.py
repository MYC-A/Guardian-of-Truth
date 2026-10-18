"""Separate real tau2-derived regression slices from authored lockboxes; no GPU."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

from audit_lora_results_cpu_20261018 import quota, read, table
from analyze_lora_standalone_audit_20261018 import metrics
from sklearn.metrics import roc_auc_score, average_precision_score


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--saved', type=Path, required=True)
    p.add_argument('--scores', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    csv.field_size_limit(2**31 - 1)
    gold = read(a.data / 'labels.jsonl')
    saved = table(a.saved)
    assert [r['id'] for r in gold] == [r['id'] for r in saved]
    assert all(r['label'] == int(s['label']) for r, s in zip(gold, saved))
    rows = [r for r in read(a.scores) if r['dataset'] == 'regression_seen']
    by = {(r['arm'], r['id']): r for r in rows}
    assert len(rows) == len(by) == 2 * len(gold)
    out = dict(scope='SEEN_REAL_TAU2_DIAGNOSTIC_NOT_NEW_HOLDOUT', gpu_calls=0,
               quota_recomputed_within_each_slice=True, sources={}, datasets={})
    for path in (a.data / 'labels.jsonl', a.saved, a.scores):
        out['sources'][str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    pools = [('real191', {'ext_tau2', 'hold_tau2h', 'hold_holdout2'}),
             ('ext_tau2', {'ext_tau2'}), ('tau2h', {'hold_tau2h'}),
             ('holdout2', {'hold_holdout2'})]
    for name, domains in pools:
        ix = [i for i, g in enumerate(gold) if g['domain'] in domains]
        y = [gold[i]['label'] for i in ix]
        hard = {j for j, i in enumerate(ix) if saved[i]['hard']}
        scores = {'qwen4b_base': [by['base', gold[i]['id']]['score'] for i in ix],
                  'qwen4b_lora': [by['adapter', gold[i]['id']]['score'] for i in ix],
                  'qwen35b_overall': [float(saved[i]['primary_score']) for i in ix],
                  'qwen35b_final': [float(saved[i]['final_score']) for i in ix]}
        v = dict(rows=len(ix), positives=sum(y), hard=len(hard),
                 ids=[gold[i]['id'] for i in ix], arms={})
        for arm, ss in scores.items():
            v['arms'][arm] = dict(roc_auc=float(roc_auc_score(y, ss)),
                average_precision=float(average_precision_score(y, ss)),
                quotas={str(q): metrics(y, quota(ss, q, hard)) for q in (.3, .4, .5, .6)})
        out['datasets'][name] = v
    assert out['datasets']['real191']['rows'] == 191
    out['limitations'] = ['Original193 inputs include2 unlabelled ext rows excluded from quality metrics',
                          'Previously viewed regression data; not an independent hidden-test estimate',
                          '35B saved prompts include different context limits and notes than4B']
    a.out.write_bytes((json.dumps(out, indent=2)+'\n').encode())
    print(json.dumps({name: {arm: v['quotas']['0.5']['f1'] for arm, v in d['arms'].items()}
                      for name, d in out['datasets'].items()}, indent=2))


if __name__ == '__main__':
    main()
