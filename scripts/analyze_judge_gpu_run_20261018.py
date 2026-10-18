"""Compare predeclared overall/MAX/final from ONE saved offline run, no fitting."""
import argparse
from collections import Counter, defaultdict
import csv
import json
import math
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'src')]
from guardian_truth.judge.decision import decide
from scripts.analyze_judge_dependencies_20261018 import metrics, rank_metrics, corr, ranks


def finite(value):
    try:
        v = float(value)
        return v if math.isfinite(v) else None
    except (ValueError, TypeError):
        return None


def paired_ci(y, before, after, groups):
    """Resample groups, frozen quota predictions; not a new threshold search."""
    vectors = defaultdict(lambda: [[0, 0, 0], [0, 0, 0]])
    for label, a, b, g in zip(y, before, after, groups):
        # TN-only groups have zero F1 counts but still belong in the resampling
        # population. Excluding them silently changes the bootstrap experiment.
        vectors[g]
        for k, pred in enumerate((a, b)):
            if pred and label:
                vectors[g][k][0] += 1
            elif pred:
                vectors[g][k][1] += 1
            elif label:
                vectors[g][k][2] += 1
    names = sorted(vectors)
    if len(names) < 2:
        return dict(groups=len(names), ci95=None, reason='INSUFFICIENT_GROUPS')
    def f1(c):
        return 2*c[0]/(2*c[0]+c[1]+c[2]) if sum(c) else 0.
    rng = random.Random(20261018)
    values = []
    for _ in range(2000):
        counts = Counter(rng.choices(names, k=len(names)))
        totals = [[sum(vectors[g][k][j]*weight for g, weight in counts.items()) for j in range(3)]
                  for k in range(2)]
        values.append(f1(totals[1])-f1(totals[0]))
    values.sort()
    return dict(groups=len(names), resamples=2000, seed=20261018, ci95=[values[49], values[1949]],
                method='paired group bootstrap; fixed original quota predictions; seen/proxy limitations apply')


def scope_result(rows, gold, indices):
    local = [rows[i] for i in indices]
    labels = [gold[i]['label'] for i in indices]
    groups = [gold[i]['group'] for i in indices]
    hard = {i for i, r in enumerate(local) if r['hard']}
    primary = {i: r['primary'] for i, r in enumerate(local) if r['primary'] is not None}
    final = {i: r['final'] for i, r in enumerate(local) if r['final'] is not None}
    union = {i: max(d[i] for d in (primary, final) if i in d) for i in primary.keys() | final.keys()}
    scores = dict(overall=primary, available_max=union, final_only=final)
    methods, predictions = {}, {}
    for method, values in scores.items():
        preds = {str(rate): decide(len(local), hard, values, rate) for rate in (.3, .4)}
        predictions[method] = preds
        exact_idx = sorted(values)
        ranking = (rank_metrics([labels[i] for i in exact_idx], [values[i] for i in exact_idx])
                   if {labels[i] for i in exact_idx} == {0, 1} else None)
        methods[method] = dict(exact_scored=len(values), missing=len(local)-len(values),
            f1_at_rate={r: metrics(labels, p) for r, p in preds.items()},
            ranking=ranking, ranking_scope='ALL_ROWS' if len(values)==len(local) else 'EXACT_SUBSET_ONLY',
            fallback='existing decide mechanical-only/no-score per missing row; not model NO')
    before = predictions['available_max']['0.4']; after = predictions['final_only']['0.4']
    result = dict(rows=len(local), positive=sum(labels), negative=len(local)-sum(labels), hard_rows=len(hard),
        methods=methods, primary_comparison=dict(candidate='final_only@.4', reference='available_max@.4',
            delta_f1=metrics(labels, after)['f1']-metrics(labels, before)['f1'],
            grouped_ci=paired_ci(labels, before, after, groups),
            fixed=sum(a!=y and b==y for a,b,y in zip(before,after,labels)),
            broken=sum(a==y and b!=y for a,b,y in zip(before,after,labels)),
            changed=[dict(position=indices[i], id=r['id'], label=labels[i], old=before[i], new=after[i])
                     for i,r in enumerate(local) if before[i]!=after[i]]))
    common = sorted(primary.keys() & final.keys())
    if common:
        xs, zs = [primary[i] for i in common], [final[i] for i in common]
        result['paired_scores'] = dict(rows=len(common), spearman=corr(ranks(xs), ranks(zs)))
    return result


def analyze(run, labels_path):
    csv.field_size_limit(2**31-1)
    gold = [json.loads(line) for line in labels_path.read_bytes().split(b'\n') if line.strip()]
    with (run/'rows.csv').open(encoding='utf-8', newline='') as stream:
        saved = list(csv.DictReader(stream))
    assert len(saved) == len(gold)
    rows = []
    for i, (r, g) in enumerate(zip(saved, gold)):
        assert int(r['index']) == g['position'] == i and r['id'] == g['id']
        assert r['label'] == str(g['label'])
        rows.append(dict(id=r['id'], primary=finite(r['primary_score']), final=finite(r['final_score']), hard=bool(r['hard'])))
    result = dict(schema='guardian-gpu-paired-ranking-v1', run=run.name, model_calls_added=0, thresholds_fitted=0,
                  weights_fitted=0, rates=[.3, .4], all_rows=scope_result(rows, gold, list(range(len(rows)))))
    common = [i for i, r in enumerate(rows) if r['primary'] is not None and r['final'] is not None]
    result['exact_intersection'] = scope_result(rows, gold, common) if common else None
    if any(g.get('domain') in ('airlines', 'healthcare', 'insurance') for g in gold):
        domains = {}
        for name, allowed in dict(external_primary={'airlines','healthcare'}, insurance={'insurance'}).items():
            idx = [i for i,g in enumerate(gold) if g.get('domain') in allowed]
            if idx:
                domains[name] = scope_result(rows, gold, idx)
        result['domains'] = domains
    records = [json.loads(line) for line in (run/'scores.jsonl').read_bytes().split(b'\n') if line.strip()]
    pre = [r for r in records if r.get('review')=='prepass']
    fin = [r for r in records if r.get('review')=='final']
    primary = {r['key']: r for r in records if 'key' in r and not r.get('review') and not r.get('extra')}
    pre_status = Counter(r.get('status', '?') for r in pre)
    result['delivery'] = dict(prepass_attempted=len(pre), prepass_status=dict(pre_status),
        truncation_rate=pre_status['TRUNCATED']/len(pre) if pre else None,
        final_records=len(fin), delivery=dict(Counter(r.get('delivery','UNKNOWN') for r in fin)),
        reasons=dict(Counter(r.get('delivery_reason') or 'NONE' for r in fin)),
        final_base_matches_saved_primary=sum(r.get('base_sha256')==primary.get(r['key'],{}).get('model_input_sha256')
                                             for r in fin if r.get('base_sha256')),
        final_with_delivered_notes=sum(r.get('delivery')=='DELIVERED' and r.get('exact') is True for r in fin),
        note_semantic_validity_proven=False)
    result['stage_done'] = next((r for r in reversed(records) if r.get('event')=='done'), None)
    result['evaluation_summary'] = json.loads((run/'summary.json').read_bytes())
    result['verdict'] = 'EXPLORATORY_NOT_PLATFORM_GAIN_OR_PROMOTION_PROOF'
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', type=Path, required=True)
    p.add_argument('--labels-file', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    result = analyze(a.run, a.labels_file)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    print(json.dumps(dict(run=a.run.name, rows=result['all_rows']['rows'],
        methods={k: v['f1_at_rate'] for k,v in result['all_rows']['methods'].items()},
        delivery=result['delivery']), indent=2))


if __name__ == '__main__':
    main()
