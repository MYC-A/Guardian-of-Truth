"""Rank-based labelling instead of a probability threshold.

Label a predeclared share of scored rows by rank, plus hard findings.
The .30 rule is experimental, not a known prevalence of future input data.

Aggregation (v3, cfg['aggregate']) over per-row score keys '<question>@<hint mode>':
  primary   the stage's primary score (first key); the production default
  mean_z    mean of per-key z-scores over cfg['aggregate_keys']
  max_z     maximum of those z-scores
  max_logit maximum available finite exact score per row (no global completeness gate)
  logistic  the linear model cfg['aggregator'], fitted offline on an INDEPENDENT labelled set
mean_z/max_z/logistic require complete inputs. max_logit is a distinct opt-in
rule that admits partial scores and has unmeasured cross-question calibration risk.
"""
from __future__ import annotations

import math

MODES = ('primary', 'mean_z', 'max_z', 'max_logit', 'logistic')


def decide(n, hard, scores, positive_rate):
    labels = [0] * n
    for i in hard:
        labels[i] = 1
    scored = [i for i in range(n) if scores.get(i) is not None]
    if scored:
        target = int(round(positive_rate * len(scored)))
        already = sum(1 for i in scored if i in hard)
        ranked = sorted((i for i in scored if i not in hard), key=lambda i: (-scores[i], i))
        for i in ranked[:max(0, target - already)]:
            labels[i] = 1
    return labels


def aggregate_inputs(cfg):
    """Score keys an aggregate needs (feature inputs excluded)."""
    mode = cfg.get('aggregate', 'primary')
    if mode == 'logistic':
        return [n for n in cfg['aggregator']['inputs'] if not n.startswith('feat:')]
    if mode in ('mean_z', 'max_z', 'max_logit'):
        return list(cfg.get('aggregate_keys') or [])
    return []


def validate_aggregate(cfg, keys):
    """Raise ValueError when the aggregate cannot be computed from the configured score keys."""
    mode = cfg.get('aggregate', 'primary')
    if mode not in MODES:
        raise ValueError('UNKNOWN_AGGREGATE: %s' % mode)
    if mode == 'max_logit' and cfg.get('require_exact_scores', True) is not True:
        raise ValueError('MAX_LOGIT_REQUIRES_EXACT_SCORES')
    if mode == 'primary':
        return
    if mode == 'logistic':
        model = cfg.get('aggregator') or {}
        sizes = {len(model.get(k) or []) for k in ('inputs', 'mean', 'std', 'weights')}
        if len(sizes) != 1 or not model.get('inputs'):
            raise ValueError('BAD_AGGREGATOR')
    needed = aggregate_inputs(cfg)
    if not needed:
        raise ValueError('AGGREGATE_WITHOUT_INPUTS')
    if len(needed) != len(set(needed)):
        raise ValueError('DUPLICATE_AGGREGATE_INPUTS')
    missing = [k for k in needed if k not in keys]
    if missing:
        raise ValueError('AGGREGATE_KEYS_NOT_SCORED: %s' % missing)


def complete_inputs(question_scores, rows, cfg):
    """Rows (of `rows`) lacking at least one aggregate input key."""
    needed = aggregate_inputs(cfg)
    return [i for i in rows if any(k not in question_scores.get(i, {}) for k in needed)]


def _zmap(values):
    xs = [v for v in values.values() if v is not None]
    if not xs:
        return {}
    mean = sum(xs) / len(xs)
    sd = math.sqrt(sum((x - mean) ** 2 for x in xs) / len(xs)) or 1.0
    return {k: (v - mean) / sd for k, v in values.items() if v is not None}


def feature_value(features, name):
    v = (features or {}).get(name, 0)
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)) and math.isfinite(v):
        return float(v)
    return 0.0


def linear_inputs(names, qscores, features):
    """Raw inputs of the logistic aggregator; None where a score key is missing."""
    out = []
    for name in names:
        if name.startswith('feat:'):
            out.append(feature_value(features, name[5:]))
        else:
            v = (qscores or {}).get(name)
            out.append(None if v is None else float(v))
    return out


def logistic_logit(model, qscores, features):
    z = float(model.get('bias', 0.0))
    for v, m, s, w in zip(linear_inputs(model['inputs'], qscores, features), model['mean'], model['std'],
                          model['weights']):
        z += w * ((m if v is None else v) - m) / (s or 1.0)
    return z


def combine(question_scores, cfg, features=None):
    """{row: {key: log-odds}} -> {row: aggregated score} for a non-primary cfg['aggregate']."""
    mode = cfg.get('aggregate', 'primary')
    rows = list(question_scores)
    if mode == 'max_logit':
        # One fixed function for every row. Missing/bounded/error inputs are absent,
        # never zero or NO. Readers admit exact scores only; finiteness is checked again.
        names = aggregate_inputs(cfg)
        out = {}
        for key, record in question_scores.items():
            values = [float(record[name]) for name in names
                      if isinstance(record.get(name), (int, float)) and not isinstance(record[name], bool)
                      and math.isfinite(record[name])]
            if values:
                out[key] = max(values)
        return out
    if mode == 'logistic':
        model = cfg['aggregator']
        return {k: logistic_logit(model, question_scores[k], (features or {}).get(k)) for k in rows}
    if mode not in ('mean_z', 'max_z'):
        raise ValueError('UNKNOWN_AGGREGATE: %s' % mode)
    names = aggregate_inputs(cfg)
    z = {n: _zmap({k: question_scores[k].get(n) for k in rows}) for n in names}
    out = {}
    for k in rows:
        vals = [z[n][k] for n in names if k in z[n]]
        if vals:
            out[k] = sum(vals) / len(vals) if mode == 'mean_z' else max(vals)
    return out
