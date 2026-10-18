"""Frozen CPU-only grouped-CV decision-rule experiment. No production mutation."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
from scipy.special import expit, logit
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from guardian_truth.judge.decision import decide

SEED = 20261019
PRIORS = (.12, .15, .20, .25, .35, .50)
RULES = ('R0', 'R1', 'R2', 'R3')
TGRID = np.linspace(-32, 32, 257)
TAUGRID = np.linspace(.05, .95, 37)


def read(path):
    return [json.loads(line) for line in path.read_bytes().splitlines() if line.strip()]


def table(path):
    with path.open(encoding='utf8', newline='') as f:
        return list(csv.DictReader(f))


def dump(path, obj):
    path.write_bytes((json.dumps(obj, indent=2, allow_nan=False) + '\n').encode())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def em_prior(log_lr, initial, tol=1e-9, iterations=1000):
    """Saerens binary EM using prior-free calibrated log likelihood ratios."""
    ll = np.asarray(log_lr, dtype=float)
    p = float(np.clip(initial, 1e-6, 1 - 1e-6))
    for step in range(iterations):
        posterior = expit(ll + logit(p))
        updated = float(np.clip(posterior.mean(), 1e-6, 1 - 1e-6))
        if abs(updated - p) < tol:
            return updated, expit(ll + logit(updated)), step + 1, True
        p = updated
    return p, expit(ll + logit(p)), iterations, False


def metrics(y, pred):
    y = np.asarray(y, dtype=bool)
    pred = np.asarray(pred, dtype=bool)
    tp = int(np.sum(y & pred)); fp = int(np.sum(~y & pred))
    fn = int(np.sum(y & ~pred)); tn = int(np.sum(~y & ~pred))
    return dict(tp=tp, fp=fp, fn=fn, tn=tn,
                f1=2 * tp / max(1, 2 * tp + fp + fn),
                precision=tp / max(1, tp + fp), recall=tp / max(1, tp + fn),
                false_discovery_rate=fp / max(1, tp + fp),
                positive_share=float(pred.mean()))


def quota(scores, hard):
    return np.array(decide(len(scores), {i: 'hard' for i in np.flatnonzero(hard)},
                           dict(enumerate(map(float, scores))), .40), dtype=bool)


def shifted_sample(y, p, rng, n=None):
    y = np.asarray(y, dtype=int)
    pi = float(y.mean())
    if not 0 < pi < 1:
        raise ValueError('ONE_CLASS_RESAMPLING_POOL')
    weights = np.where(y == 1, p / pi, (1 - p) / (1 - pi))
    return rng.choice(len(y), size=len(y) if n is None else n,
                      replace=True, p=weights / weights.sum())


def score_grid(y, values, grid, hard):
    pred = (np.asarray(values)[:, None] > grid[None, :]) | np.asarray(hard)[:, None]
    tp = (pred & np.asarray(y, dtype=bool)[:, None]).sum(0)
    pp = pred.sum(0)
    return 2 * tp / np.maximum(1, pp + np.sum(y))


def crossfit(scores, y, hard, groups):
    splitter = GroupKFold(5, shuffle=True, random_state=SEED)
    n = len(y)
    params = {k: np.zeros(n) for k in ('threshold', 'slope', 'intercept', 'train_prior', 'tau')}
    folds = []
    for fold, (train, test) in enumerate(splitter.split(scores, y, groups)):
        assert not set(groups[train]) & set(groups[test])
        inner = GroupKFold(5, shuffle=True, random_state=SEED + 100 + fold)
        utility_t = np.zeros(len(TGRID)); utility_tau = np.zeros(len(TAUGRID))
        for inner_fold, (fit_local, val_local) in enumerate(inner.split(scores[train], y[train], groups[train])):
            fit = train[fit_local]; val = train[val_local]
            assert not set(groups[fit]) & set(groups[val])
            model = LogisticRegression(C=1, solver='lbfgs', max_iter=1000).fit(scores[fit, None], y[fit])
            a = float(model.coef_[0, 0]); b = float(model.intercept_[0]); pi = float(y[fit].mean())
            for j, p in enumerate((*PRIORS, None)):
                rng = np.random.default_rng(SEED + fold * 1000 + inner_fold * 50 + j)
                local = np.arange(len(val)) if p is None else shifted_sample(y[val], p, rng)
                ix = val[local]; yy = y[ix]
                utility_t += score_grid(yy, scores[ix], TGRID, hard[ix])
                ll = a * scores[ix] + b - logit(pi)
                _, posterior, _, _ = em_prior(ll, pi)
                utility_tau += score_grid(yy, posterior, TAUGRID, hard[ix])
        t = float(TGRID[np.argmax(utility_t)])
        tau = float(TAUGRID[np.argmax(utility_tau)])
        model = LogisticRegression(C=1, solver='lbfgs', max_iter=1000).fit(scores[train, None], y[train])
        values = dict(threshold=t, slope=float(model.coef_[0, 0]), intercept=float(model.intercept_[0]),
                      train_prior=float(y[train].mean()), tau=tau)
        for k, v in values.items(): params[k][test] = v
        folds.append(dict(fold=fold, train_indices=train.tolist(), test_indices=test.tolist(), **values))
        print(json.dumps(dict(event='crossfit', fold=fold, threshold=t, tau=tau)), flush=True)
    return params, folds


def predict_all(scores, hard, params, ix, perturb=None):
    ss = scores[ix].copy()
    if perturb is not None: ss += perturb
    ll = params['slope'][ix] * ss + params['intercept'][ix] - logit(params['train_prior'][ix])
    prior, posterior, iterations, converged = em_prior(ll, float(params['train_prior'][ix].mean()))
    h = hard[ix]
    pred = dict(R0=quota(ss, h), R1=(ss > 0) | h,
                R2=(ss > params['threshold'][ix]) | h,
                R3=(posterior > params['tau'][ix]) | h)
    return pred, dict(estimated_prior=prior, iterations=iterations, converged=converged)


def measure_noise(runs, audit):
    records = []; metadata = []
    for name in ('dev_replay_r1', 'dev_replay_r2', 'dev_replay_r3'):
        root = runs / name
        rows = {r['key']: r for r in read(root / 'scores.jsonl') if r.get('arm') == 'strict'}
        prompts = {r['key']: r for r in read(root / 'prompts.jsonl') if r.get('arm') == 'strict'}
        assert len(rows) == len(prompts) == 520
        for k, r in rows.items():
            assert r['exact'] and math.isfinite(r['final_score'])
            assert r['input_sha256'] == prompts[k]['input_sha256']
            assert r['input_token_sha256'] == prompts[k]['input_token_sha256']
            assert hashlib.sha256(prompts[k]['text'].encode('utf8', 'surrogatepass')).hexdigest() == r['input_sha256']
        records.append((rows, prompts))
        metadata.append(dict(run=name, scores_sha256=sha(root / 'scores.jsonl'),
                             prompts_sha256=sha(root / 'prompts.jsonl'), done=read_json(root / 'DONE.json')))
    diffs = []
    for left in range(3):
        for right in range(left + 1, 3):
            x, xp = records[left]; z, zp = records[right]
            assert x.keys() == z.keys()
            for key in x:
                assert xp[key]['text'] == zp[key]['text']
                assert x[key]['input_token_sha256'] == z[key]['input_token_sha256']
                diffs.append(x[key]['final_score'] - z[key]['final_score'])
    base_audit = read_json(audit)
    assert base_audit['numerical_checks']['vanilla_vs_disabled']['all_exact']
    return dict(qwen35b_vllm=dict(sd_obs=float(np.std(diffs, ddof=1) / np.sqrt(2)),
                 mean_difference=float(np.mean(diffs)), max_abs_difference=float(np.max(np.abs(diffs))),
                 matched_prompts=520, pairs=len(diffs), scope='strict final scorer only, reused notes; not full pipeline repeat',
                 differences=diffs, evidence=metadata),
                qwen4b_transformers=dict(sd_obs=0.0, rows=78, source_sha256=sha(audit),
                 scope='base standalone audit only; no claim of zero noise for future LoRA or different runtime'))


def read_json(path):
    return json.loads(path.read_bytes())


def run(a):
    a.out.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    dump(a.out / 'START.json', dict(seed=SEED, rules=list(RULES), priors=list(PRIORS),
         bootstrap=1000, noise_repeats=200, script_sha256=sha(Path(__file__)),
         protocol_sha256=sha(ROOT / 'docs/judge_20261013/V3_A_DECISION_RULE_PROTOCOL.md')))
    try:
        rows = table(a.runs / 'regression_r1/rows.csv')
        gold = read(a.data / 'regression_seen/labels.jsonl')
        assert len(rows) == len(gold) == 397 and [r['id'] for r in rows] == [g['id'] for g in gold]
        y = np.array([g['label'] for g in gold]); scores = np.array([float(r['score']) for r in rows])
        hard = np.array([bool(r['hard']) for r in rows]); groups = np.array([g['conversation'] for g in gold])
        assert all(int(r['label']) == g['label'] for r, g in zip(rows, gold))
        assert np.isfinite(scores).all()
        assert all(float(r['score']) == max(float(r['primary_score']), float(r['final_score'])) for r in rows)
        assert abs(metrics(y, quota(scores, hard))['f1'] - .7512437810945274) < 1e-12
        noise = measure_noise(a.runs, ROOT / 'docs/judge_20261013/lora_baseline_audit_evidence_20261018/ANALYSIS.json')
        dump(a.out / 'NOISE_OBSERVATIONS.json', noise)
        params, folds = crossfit(scores, y, hard, groups)
        dump(a.out / 'FOLDS.json', folds)
        dump(a.out / 'PARAMETERS.json', {k: v.tolist() for k, v in params.items()})
        saved = [dict(index=i, id=r['id'], conversation=groups[i], label=int(y[i]),
                      score=float(scores[i]), hard=bool(hard[i]), **{k: float(v[i]) for k, v in params.items()})
                 for i, r in enumerate(rows)]
        with gzip.open(a.out / 'CROSSFIT_INPUTS.jsonl.gz', 'wt', encoding='utf8') as f:
            for r in saved: f.write(json.dumps(r) + '\n')
        valid = {r['id'] for r in table(a.runs / 'valid46_r1/rows.csv')}
        pools = dict(seen397=np.arange(397), real191=np.array([i for i, g in enumerate(gold)
                     if g['domain'] in ('ext_tau2', 'hold_tau2h', 'hold_holdout2')]),
                     valid46=np.array([i for i, r in enumerate(rows) if r['id'] in valid]))
        result = dict(schema='guardian-v3-A-v1', cohorts={}, noise_observations={
                      k: {x: z for x, z in v.items() if x not in ('differences', 'evidence')} for k, v in noise.items()})
        draws = {}; ds = [(.05, '0.05'), (.1, '0.1'), (.25, '0.25'), (.5, '0.5'), (1., '1.0'),
                         (noise['qwen35b_vllm']['sd_obs'], 'observed')]
        for cohort, pool in pools.items():
            result['cohorts'][cohort] = dict(rows=len(pool), positives=int(y[pool].sum()),
                    groups=len(set(groups[pool])), points={})
            native = float(y[pool].mean()); rng = np.random.default_rng(SEED + len(pool))
            for pi, requested in enumerate((*PRIORS, None)):
                point = 'native' if requested is None else str(requested)
                ix = pool if requested is None else pool[shifted_sample(y[pool], requested, rng)]
                draws[cohort + ':' + point] = ix.tolist()
                predictions, em = predict_all(scores, hard, params, ix)
                m = {k: metrics(y[ix], pred) for k, pred in predictions.items()}
                info = dict(requested_prior=native if requested is None else requested,
                    actual_prior=float(y[ix].mean()), em=em, metrics=m, ci_f1_difference={}, noise={})
                if cohort != 'valid46':
                    delta = {k: [] for k in RULES[1:]}; skipped = 0
                    unique = np.unique(groups[pool]); positions = {g: pool[groups[pool] == g] for g in unique}
                    brng = np.random.default_rng(SEED + len(pool) * 100 + pi)
                    with gzip.open(a.out / (cohort + '_' + point + '_bootstrap.jsonl.gz'), 'wt', encoding='utf8') as f:
                        for b in range(1000):
                            choice = brng.choice(unique, len(unique), replace=True)
                            bi = np.concatenate([positions[g] for g in choice])
                            if requested is not None:
                                if not 0 < y[bi].mean() < 1: skipped += 1; continue
                                bi = bi[shifted_sample(y[bi], requested, brng)]
                            bp, be = predict_all(scores, hard, params, bi)
                            bm = {k: metrics(y[bi], pred)['f1'] for k, pred in bp.items()}
                            for k in delta: delta[k].append(bm[k] - bm['R0'])
                            f.write(json.dumps(dict(iteration=b, group_draws=choice.tolist(),
                                    row_indices=bi.tolist(), f1=bm, em_converged=be['converged'])) + '\n')
                    for k, dd in delta.items():
                        lo, hi = np.quantile(dd, [.025, .975])
                        info['ci_f1_difference'][k] = dict(point=m[k]['f1'] - m['R0']['f1'],
                            low=float(lo), high=float(hi), samples=len(dd), skipped=skipped)
                for sd, name in ds:
                    nrng = np.random.default_rng(SEED + len(pool) * 10 + pi)
                    flips = {k: [] for k in RULES}; df1 = {k: [] for k in RULES}
                    for rep in range(200):
                        epsilon = nrng.normal(0., sd, len(ix))
                        npred, _ = predict_all(scores, hard, params, ix, epsilon)
                        for k in RULES:
                            flips[k].append(float(np.mean(npred[k] != predictions[k])))
                            df1[k].append(metrics(y[ix], npred[k])['f1'] - m[k]['f1'])
                    nonhard_selected = np.flatnonzero(predictions['R0'] & ~hard[ix])
                    boundary = float(np.min(scores[ix][nonhard_selected])) if len(nonhard_selected) else float('inf')
                    slope = params['slope'][ix]
                    with np.errstate(divide='ignore', invalid='ignore'):
                        bound3 = (logit(params['tau'][ix]) - logit(em['estimated_prior'])
                                  - params['intercept'][ix] + logit(params['train_prior'][ix])) / slope
                    boundaries = dict(R0=boundary, R1=0., R2=params['threshold'][ix], R3=bound3)
                    info['noise'][name] = dict(sd=sd, arms={k: dict(
                        changed_mean=float(np.mean(flips[k])), changed_p95=float(np.quantile(flips[k], .95)),
                        f1_change_mean=float(np.mean(df1[k])), f1_change_low=float(np.quantile(df1[k], .025)),
                        f1_change_high=float(np.quantile(df1[k], .975)),
                        near_boundary_share=float(np.mean(np.abs(scores[ix] - boundaries[k]) <= 2 * sd))) for k in RULES})
                result['cohorts'][cohort]['points'][point] = info
                dump(a.out / 'RESULTS.partial.json', result)
                print(json.dumps(dict(event='cohort_point', cohort=cohort, point=point,
                        f1={k: v['f1'] for k, v in m.items()}, seconds=time.monotonic() - start)), flush=True)
        gates = {}
        for k in RULES[1:]:
            conditions = dict(low_prevalence_gain=True, high_native_no_regression=True, measured_noise_stability=True)
            for cohort in ('seen397', 'real191'):
                ps = result['cohorts'][cohort]['points']
                for point in ('0.12', '0.2'):
                    d = ps[point]['ci_f1_difference'][k]
                    conditions['low_prevalence_gain'] &= d['point'] >= .03 and d['low'] > 0
                for point in ('0.5', 'native'):
                    conditions['high_native_no_regression'] &= ps[point]['metrics'][k]['f1'] >= ps[point]['metrics']['R0']['f1'] - .01
                conditions['measured_noise_stability'] &= all(v['noise']['observed']['arms'][k]['changed_mean'] <= .03 for v in ps.values())
            gates[k] = dict(conditions={n: bool(v) for n, v in conditions.items()}, passes=all(conditions.values()))
        selected = next((k for k in RULES[1:] if gates[k]['passes']), 'R0')
        result.update(gates=gates, selected=selected, production_changed=False,
                      limitations=['Previously viewed overlapping cohorts, not hidden-test evidence',
                                   'Prior shift simulated by resampling; cannot reconstruct unknown domain shift',
                                   'Intervals conditional on cross-fit parameters, without calibration refit',
                                   'Runtime noise observed only for frozen-note final scores on dev520'])
        dump(a.out / 'BATCH_INDICES.json', draws)
        dump(a.out / 'RESULTS.json', result)
        dump(a.out / 'DONE.json', dict(complete=True, selected=selected, seconds=time.monotonic()-start,
             rows=397, script_sha256=sha(Path(__file__)), sources={str(p):sha(p) for p in
             (a.runs/'regression_r1/rows.csv', a.data/'regression_seen/labels.jsonl')}))
        print(json.dumps(dict(event='complete', selected=selected, gates=gates)), flush=True)
    except Exception as e:
        dump(a.out / 'DONE.json', dict(complete=False, error_type=type(e).__name__,
             error=str(e), seconds=time.monotonic()-start))
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', type=Path, required=True)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    run(parser.parse_args())
