"""Calibrate cascade thresholds offline from a triage-only run and an existing B2 run.

    python scripts/cascade_calibrate.py --scores WORK/triage_scores.jsonl --labels valid.parquet \
        [--b2 B2_predictions.parquet] [--output calib.json]

Prints triage AUC, best direct threshold, and the F1-vs-k escalation curve
(k = number of rows given to B2 in priority order; wall time ~ k * row cost / workers).
"""
import argparse
import json
import pandas as pd

from guardian_truth.cascade.calibrate import auc, best_threshold, escalation_curve, metrics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--scores', required=True)
    parser.add_argument('--labels', required=True)
    parser.add_argument('--b2')
    parser.add_argument('--or-threshold', type=float)
    parser.add_argument('--output')
    options = parser.parse_args()
    scores = {}
    views = {}
    for line in open(options.scores, encoding='utf-8'):
        item = json.loads(line)
        scores[item['id']] = item['p']
        views[item['id']] = item.get('views') or {}
    frame = pd.read_parquet(options.labels)
    labels = {i: int(y) for i, y in zip(frame['id'], frame['label'])}
    result = dict(rows=len(labels), unreadable=sum(scores.get(i) is None for i in labels),
                  auc=auc(scores, labels), triage_best=best_threshold(scores, labels))
    for view in sorted({v for d in views.values() for v in d}):
        result[f'auc_{view}'] = auc({i: views.get(i, {}).get(view) for i in labels}, labels)
    if options.b2:
        b2f = pd.read_parquet(options.b2)
        b2 = {i: int(y) for i, y in zip(b2f['id'], b2f['label'])}
        result['b2_alone'] = metrics([(labels[i], b2[i]) for i in labels])
        t = result['triage_best']['threshold']
        result['curve'] = escalation_curve(scores, labels, b2, t, options.or_threshold)
        if options.or_threshold is None:
            ors = []
            for cand in sorted({s for s in scores.values() if s is not None}):
                m = metrics([(labels[i], int(b2[i] == 1 or (scores.get(i) is not None and scores[i] >= cand)))
                             for i in labels])
                ors.append(dict(or_threshold=cand, **m))
            result['or_best'] = max(ors, key=lambda r: (r['F1'], r['or_threshold'])) if ors else None
    text = json.dumps(result, indent=2, ensure_ascii=False)
    print(text)
    if options.output:
        open(options.output, 'w', encoding='utf-8').write(text)


if __name__ == '__main__':
    main()
