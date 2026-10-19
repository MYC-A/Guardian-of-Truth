"""Frozen E2 comparison; no model, eval-label, threshold-grid or production changes."""
import argparse
from collections import defaultdict
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np
from scipy.special import expit
from scipy.stats import rankdata
from sklearn.metrics import roc_auc_score, average_precision_score

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from v3_analyze_hours import metrics, quota
from v3_decision_rule import shifted_sample

SEED = 20261019
PRIORS = (.12, .15, .20, .25, .35, .50, None)
VGRID = (0., .01, .025, .05, .10, .20)


def read(path):
    return [json.loads(line) for line in path.read_bytes().splitlines() if line.strip()]


def table(path):
    with path.open(encoding='utf8', newline='') as f:
        return list(csv.DictReader(f))


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf8')


def evaluated(y, base, adapter, control, hard, v):
    """Percentile ranks and quota are recomputed in this supplied batch."""
    y = np.asarray(y, dtype=int)
    base = np.asarray(base, dtype=float)
    adapter = np.asarray(adapter, dtype=float)
    hard = np.asarray(hard, dtype=bool)
    blend = (rankdata(base) + rankdata(adapter)) / (2 * len(y))
    scores = dict(current35b=base, adapter=adapter, base4b=np.asarray(control), blend=blend)
    predictions = {name: np.array(quota(s, set(np.flatnonzero(hard))), dtype=int)
                   for name, s in scores.items()}
    predictions['veto'] = predictions['current35b'].copy()
    predictions['veto'][(expit(adapter) < v) & ~hard] = 0
    return scores, predictions, {name: metrics(y, p) for name, p in predictions.items()}


def choose_veto(y, base, adapter, control, hard):
    trials = []
    for v in VGRID:
        _, _, m = evaluated(y, base, adapter, control, hard, v)
        old, new = m['current35b'], m['veto']
        trials.append(dict(v=v, fp_removed=old['fp']-new['fp'], tp_lost=old['tp']-new['tp']))
    eligible = [r for r in trials if r['tp_lost'] == 0]
    selected = min(eligible, key=lambda r: (-r['fp_removed'], r['v']))['v']
    return dict(selected_v=selected, trials=trials, selection_partition='DEV154_ONLY',
                q_is_calibrated_probability=False, semantic_verifier=False)


def matched_prefix(y, scores, target, hard):
    selected = set(np.flatnonzero(hard))
    found = sum(y[i] for i in selected)
    for i in sorted(range(len(y)), key=lambda i: (-scores[i], i)):
        if found >= target:
            break
        if i not in selected:
            selected.add(i)
            found += y[i]
    return metrics(y, [int(i in selected) for i in range(len(y))])


def compare(y, base, adapter, control, hard, v):
    scores, pred, m = evaluated(y, base, adapter, control, hard, v)
    target = m['current35b']['tp']
    matched = {name: matched_prefix(y, s, target, hard) for name, s in scores.items()}
    old = pred['current35b']
    changes = {}
    for name, p in pred.items():
        changes[name] = dict(tp_gained=int(sum((old == 0) & (p == 1) & (y == 1))),
                             tp_lost=int(sum((old == 1) & (p == 0) & (y == 1))),
                             fp_removed=int(sum((old == 1) & (p == 0) & (y == 0))),
                             fp_added=int(sum((old == 0) & (p == 1) & (y == 0))))
    result = dict(actual_prior=float(np.mean(y)), metrics=m, changes=changes,
                  matched_target_tp=target, matched_recall=matched,
                  all_positive=metrics(y, [1]*len(y)))
    if len(set(y)) == 2:
        result['ranking'] = {k: dict(auc=float(roc_auc_score(y, s)),
                                    ap=float(average_precision_score(y, s))) for k, s in scores.items()}
    return result, scores, pred


def interval(values):
    return dict(ci95=list(map(float, np.quantile(values, [.025, .975]))) if values else None,
                valid_replicates=len(values))


def analyze_cohort(name, cohort, v, out, ordinal, draws=1000):
    y = np.array([r['label'] for r in cohort], dtype=int)
    b = np.array([r['current35b'] for r in cohort]); a = np.array([r['adapter'] for r in cohort])
    c = np.array([r['base4b'] for r in cohort]); h = np.array([r['hard'] for r in cohort], dtype=bool)
    grouped = defaultdict(list)
    for i, r in enumerate(cohort):
        grouped[r['group']].append(i)
    keys = sorted(grouped)
    priors = (None,) if name == 'valid46' else PRIORS
    results = dict(rows=len(y), positive=int(sum(y)), groups=len(keys), points={})
    for j, prior in enumerate(priors):
        point = 'native' if prior is None else str(prior)
        rng = np.random.default_rng(SEED + ordinal*1000 + j)
        ix = np.arange(len(y)) if prior is None else shifted_sample(y, prior, rng)
        result, _, _ = compare(y[ix], b[ix], a[ix], c[ix], h[ix], v)
        result['row_indices'] = ix.tolist()
        result['requested_prior'] = float(y.mean()) if prior is None else prior
        records = {arm: defaultdict(list) for arm in ('adapter', 'base4b', 'blend', 'veto')}
        skipped = 0
        brng = np.random.default_rng(SEED + ordinal*10000 + j + 500)
        with gzip.open(out/(name+'_'+point+'_draws.jsonl.gz'), 'wt', encoding='utf8') as stream:
            for rep in range(draws):
                picked = brng.choice(keys, len(keys), replace=True)
                bi = np.array([i for key in picked for i in grouped[str(key)]])
                if len(set(y[bi])) != 2:
                    skipped += 1
                    continue
                if prior is not None:
                    bi = bi[shifted_sample(y[bi], prior, brng)]
                yy = y[bi]
                if len(set(yy)) != 2:
                    skipped += 1
                    continue
                rr, _, _ = compare(yy, b[bi], a[bi], c[bi], h[bi], v)
                reference = rr['metrics']['current35b']
                ref_fp = rr['matched_recall']['current35b']['fp']
                for arm, values in records.items():
                    m = rr['metrics'][arm]
                    values['f1_difference'].append(m['f1']-reference['f1'])
                    values['fp_difference'].append(m['fp']-reference['fp'])
                    values['tp_difference'].append(m['tp']-reference['tp'])
                    if arm != 'veto':
                        afp = rr['matched_recall'][arm]['fp']
                        values['matched_fp_difference'].append(afp-ref_fp)
                        if ref_fp:
                            values['matched_fp_relative_reduction'].append((ref_fp-afp)/ref_fp)
                stream.write(json.dumps(dict(rep=rep, group_draws=picked.tolist(),
                                             row_indices=bi.tolist(), actual_prior=float(yy.mean())))+'\n')
        result['paired_bootstrap'] = dict(draws=draws, one_class_skipped=skipped,
            arms={arm: {key: interval(value) for key, value in values.items()} for arm, values in records.items()},
            zero_reference_fp_skipped={arm: len(records[arm]['matched_fp_difference'])-
                len(records[arm]['matched_fp_relative_reduction']) for arm in ('adapter','base4b','blend')},
            ranks_quota_target_recomputed=True, veto_threshold_refitted=False)
        results['points'][point] = result
        dump(out/'RESULTS.partial.json', {name: results})
        print(json.dumps(dict(cohort=name, point=point,
                              f1={k: round(m['f1'], 4) for k, m in result['metrics'].items()})), flush=True)
    return results


def main():
    parser = argparse.ArgumentParser()
    for name in ('reference', 'frozen', 'run', 'protected', 'saved', 'out'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(exist_ok=False)
    reference = json.loads((args.reference/'DONE.json').read_bytes())
    assert reference['complete'] and reference['exact_primary'] == reference['exact_final'] == 455
    mapping = json.loads((args.reference/'INPUTS.json').read_bytes())['rows']
    current = table(args.reference/'run/rows.csv')
    assert len(current) == len(mapping) == 455
    lookup = {}
    for meta, row in zip(mapping, current):
        assert meta['id'] == row['id']
        assert all(math.isfinite(float(row[k])) for k in ('score','primary_score','final_score'))
        assert float(row['score']) == max(float(row['primary_score']), float(row['final_score']))
        lookup[meta['partition'],meta['id']] = row
    scores = read(args.run/'scores.jsonl')
    saved4 = {(r['partition'], r['arm'], r['id']): r for r in scores}
    assert len(saved4) == len(scores) == 1834 and all(r['exact'] for r in scores)
    cohorts = {}
    for part in ('dev','holdout'):
        cohorts[part] = []
        for g in read(args.frozen/(part+'.jsonl')):
            r = lookup[part,g['id']]
            assert g['label'] == int(r['label'])
            cohorts[part].append(dict(id=g['id'], label=g['label'],group=g['split_component'],
                current35b=float(r['score']), adapter=saved4[part,'adapter',g['id']]['score'],
                base4b=saved4[part,'base',g['id']]['score'], hard=bool(r['hard']),
                source=g['source'], family=g['family']))
    d = cohorts['dev']
    selected = choose_veto(*[np.array([r[k] for r in d]) for k in
                            ('label','current35b','adapter','base4b','hard')])
    dump(args.out/'DEV_VETO_SELECTION.json', selected)  # Written before HOLDOUT analysis.
    v = selected['selected_v']
    gold = read(args.protected/'regression_seen/labels.jsonl')
    old = table(args.saved/'regression_r1/rows.csv')
    assert len(gold) == len(old) == 397
    valid = {r['id'] for r in table(args.saved/'valid46_r1/rows.csv')}
    cohorts['seen397'] = []
    for g,r in zip(gold,old):
        assert g['id'] == r['id'] and g['label'] == int(r['label'])
        cohorts['seen397'].append(dict(id=g['id'],label=g['label'],group=g['conversation'],
            current35b=float(r['score']), adapter=saved4['regression_seen','adapter',g['id']]['score'],
            base4b=saved4['regression_seen','base',g['id']]['score'],hard=bool(r['hard']),domain=g['domain']))
    cohorts['real191'] = [r for r in cohorts['seen397'] if r['domain'] in
                          {'ext_tau2','hold_tau2h','hold_holdout2'}]
    cohorts['valid46'] = [r for r in cohorts['seen397'] if r['id'] in valid]
    dump(args.out/'COHORTS.json', cohorts)
    results = dict(status='EXPLORATORY_ONLY', protocol_commit='b037ed69',
                   veto_selection=selected, cohorts={}, production_changed=False,
                   human_reviewed=False, prior_shift_is_not_domain_shift=True)
    for ordinal, name in enumerate(('holdout','seen397','real191','valid46')):
        results['cohorts'][name] = analyze_cohort(name, cohorts[name], v, args.out, ordinal)
        dump(args.out/'RESULTS.json', results)
    with (args.out/'CHANGES.jsonl').open('w',encoding='utf8') as stream:
        for name, cohort in cohorts.items():
            arrays = [np.array([r[k] for r in cohort]) for k in
                      ('label','current35b','adapter','base4b','hard')]
            _, pp, _ = evaluated(*arrays, v)
            for arm in ('adapter','blend','veto'):
                for i,r in enumerate(cohort):
                    if pp[arm][i] != pp['current35b'][i]:
                        stream.write(json.dumps(dict(cohort=name,arm=arm,baseline=int(pp['current35b'][i]),
                                                     candidate=int(pp[arm][i]),**r))+'\n')
    dump(args.out/'DONE.json', dict(complete=True, protocol_commit='b037ed69',
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        inputs_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in
            [args.reference/'DONE.json',args.reference/'run/rows.csv',args.run/'scores.jsonl',
             args.frozen/'FROZEN.json',args.saved/'regression_r1/rows.csv',
             args.protected/'regression_seen/labels.jsonl']}))


if __name__ == '__main__':
    main()
