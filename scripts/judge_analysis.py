"""Offline A/B analysis of judge runs on a LABELLED, INDEPENDENT development file. Labels are read only here.

  python scripts/judge_analysis.py --input dev.parquet --run runs/a [--run runs/b ...] --out runs/ab.json

Each --run is an eval_judge_valid.py --out directory (stage_input.jsonl, scores.jsonl, summary.json).
Checks before any number is reported:
  * every run's stage_input.jsonl matches the input file row by row (position and SHA256 of prompt and
    response), so all runs saw identical rows;
  * every input position occurs exactly once, no row has a second primary record or a repeated score key;
  * scores are finite and exact (exact != true and bounded scores are skipped and counted), keys follow
    '<question>@<on|off>';
  * comparisons use only the INTERSECTION of rows scored by every compared variant (coverage reported);
  * groups (id prefix before the first ':') are the unit of the bootstrap and of cross-validation.
Variants: every score key of every run ('run:key'); mean_z / max_z / out-of-fold logistic over the keys of
one run are reported for information. Hint A/B: '<q>@on' vs '<q>@off' of the same run share prompts that
differ only in the hint block; the delta is also reported on rows where hints were shown.
Decision rule: a variant replaces the reference (default: first run's primary key) only when the lower end
of the grouped 95% interval of delta AUC is > 0. Files with fewer than --min-rows rows (valid46) are
reported as smoke only: no promotion is computed.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import random
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / 'src')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from guardian_truth.judge.decision import combine, linear_inputs, logistic_logit  # noqa: E402
from guardian_truth.judge.prompting import HINT_MODES, QUESTIONS  # noqa: E402

TARGET_PREVALENCE = 130 / 548
RATES = (0.25, 0.30, 0.35, 0.40)
KEY = re.compile(r'^(%s)@(%s)$' % ('|'.join(QUESTIONS), '|'.join(HINT_MODES)))


def sha(text):
    return hashlib.sha256((text or '').encode('utf-8')).hexdigest()


def auc(labels, scores):
    pairs = sorted(zip(scores, labels), key=lambda p: p[0])
    n = len(pairs)
    npos = sum(1 for _, y in pairs if y == 1)
    nneg = n - npos
    if not npos or not nneg:
        return None
    rank_sum, i = 0.0, 0
    while i < n:
        j = i
        while j + 1 < n and pairs[j + 1][0] == pairs[i][0]:
            j += 1
        rank_sum += ((i + j) / 2 + 1) * sum(1 for k in range(i, j + 1) if pairs[k][1] == 1)
        i = j + 1
    return (rank_sum - npos * (npos + 1) / 2) / (npos * nneg)


def groups_of(ids, pattern=r'^([^:]+)'):
    rx = re.compile(pattern)
    out = []
    for identifier in ids:
        m = rx.search(str(identifier))
        out.append(m.group(1) if m and m.groups() else str(identifier))
    return out


def group_bootstrap(groups, statistic, iterations=1000, seed=0):
    members = defaultdict(list)
    for i, g in enumerate(groups):
        members[g].append(i)
    names = sorted(members)
    if len(names) < 5:
        return None
    rng = random.Random(seed)
    values = []
    for _ in range(iterations):
        v = statistic([i for _ in names for i in members[rng.choice(names)]])
        if v is not None:
            values.append(v)
    if len(values) < 20:
        return None
    values.sort()
    return [round(values[int(0.025 * len(values))], 4), round(values[int(0.975 * len(values)) - 1], 4)]


def f1_at_rate(labels, scores, rate, prevalence=None, hard=()):
    pos = sum(labels)
    neg = len(labels) - pos
    if not pos or not neg:
        return None
    w = 1.0 if prevalence is None else pos * (1 - prevalence) / (prevalence * neg)
    weight = [1.0 if y else w for y in labels]
    total, hard = sum(weight), set(hard)
    order = sorted(range(len(labels)), key=lambda i: (i not in hard, -scores[i], i))
    taken = tp = fp = 0.0
    for i in order:
        if i not in hard and taken >= rate * total:
            break
        taken += weight[i]
        if labels[i]:
            tp += 1
        else:
            fp += weight[i]
    return round(2 * tp / (2 * tp + fp + (pos - tp)), 4) if tp else 0.0


def fit_logistic(rows, y, l2=1.0, iterations=50):
    import numpy as np
    d = len(rows[0]) if rows else 0
    cols = [[r[j] for r in rows if r[j] is not None] for j in range(d)]
    means = [sum(c) / len(c) if c else 0.0 for c in cols]
    stds = [math.sqrt(sum((x - m) ** 2 for x in c) / len(c)) or 1.0 if c else 1.0 for c, m in zip(cols, means)]
    X = np.array([[0.0 if r[j] is None else (r[j] - means[j]) / stds[j] for j in range(d)] + [1.0] for r in rows])
    t, w = np.array(y, dtype=float), np.zeros(d + 1)
    reg = np.eye(d + 1) * l2
    reg[d, d] = 0.0
    for _ in range(iterations):
        p = 1 / (1 + np.exp(-np.clip(X @ w, -30, 30)))
        step = np.linalg.solve((X * (p * (1 - p))[:, None]).T @ X + reg + np.eye(d + 1) * 1e-6, X.T @ (p - t) + reg @ w)
        w -= step
        if float(np.max(np.abs(step))) < 1e-6:
            break
    return dict(mean=means, std=stds, weights=[float(v) for v in w[:d]], bias=float(w[d]))


def oof_logistic(inputs, idx, qs, groups, labels, k=5, seed=0):
    names = sorted({groups[i] for i in idx})
    random.Random(seed).shuffle(names)
    fold = {g: n % k for n, g in enumerate(names)}
    out = {}
    for f in range(k):
        train = [i for i in idx if fold[groups[i]] != f]
        test = [i for i in idx if fold[groups[i]] == f]
        if not test or len({labels[i] for i in train}) < 2:
            continue
        model = dict(inputs=inputs, **fit_logistic([linear_inputs(inputs, qs[i], {}) for i in train],
                                                    [labels[i] for i in train]))
        for i in test:
            out[i] = logistic_logit(model, qs[i], {})
    return out


def read_labelled(path):
    import pandas as pd
    path = Path(path)
    with path.open('rb') as stream:
        parquet = stream.read(4) == b'PAR1'
    frame = pd.read_parquet(path) if parquet else pd.read_csv(path)
    for column in ('id', 'prompt', 'response', 'label'):
        if column not in frame.columns:
            raise SystemExit('labelled file needs column %s' % column)
    return ([str(v) for v in frame['id']], [int(v) for v in frame['label']],
            [(sha(str(p)), sha(str(r))) for p, r in zip(frame['prompt'], frame['response'])])


def read_run(run_dir, digests):
    """Scores of one run with integrity checks. Problems (any one blocks every comparison): stage rows that do
    not cover each input position exactly once with matching SHA256, labels in the stage input, a second
    primary record for a row, a repeated extra score key for a row, keys outside the schema, non-finite or
    out-of-range rows. Inexact results (primary exact != true, extra keys in "bounded") are skipped and counted."""
    run_dir = Path(run_dir)
    problems = []
    stage = [json.loads(l) for l in (run_dir / 'stage_input.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
    positions = [int(row['key']) for row in stage]
    if sorted(positions) != list(range(len(digests))):
        problems.append('STAGE_POSITIONS_NOT_A_PERMUTATION (%d rows, %d unique, input %d)'
                        % (len(positions), len(set(positions)), len(digests)))
    for row in stage:
        k = int(row['key'])
        if not 0 <= k < len(digests) or (sha(row['prompt']), sha(row['response'])) != digests[k]:
            problems.append('ROW_MISMATCH key %d' % k)
            break
        if 'label' in row or 'explanation' in row:
            problems.append('LABEL_LEAKED_INTO_STAGE_INPUT')
            break
    qs, shown, done = defaultdict(dict), {}, {}
    primary_seen, extra_seen = set(), set()
    skipped = dict(inexact_primary=0, unscored_primary=0, inexact_extra=0)
    for line in (run_dir / 'scores.jsonl').read_text(encoding='utf-8').splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            break
        if item.get('event') == 'done':
            done = item
        if 'key' not in item or 'event' in item:
            continue
        k = int(item['key'])
        if not 0 <= k < len(digests):
            problems.append('KEY_OUT_OF_RANGE %d' % k)
            continue
        if item.get('extra'):
            bounded = item.get('bounded') or {}
            skipped['inexact_extra'] += len(bounded)
            for name, v in (item.get('scores') or {}).items():
                if (k, name) in extra_seen:
                    problems.append('DUPLICATE_EXTRA %s row %d' % (name, k))
                extra_seen.add((k, name))
                if name in bounded:
                    continue
                if not KEY.match(name):
                    problems.append('BAD_KEY %s' % name)
                elif isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
                    qs[k][name] = float(v)
                else:
                    problems.append('NON_FINITE %s row %d' % (name, k))
            continue
        if k in primary_seen:
            problems.append('DUPLICATE_PRIMARY row %d' % k)
            continue
        primary_seen.add(k)
        if item.get('score') is None:
            skipped['unscored_primary'] += 1
            continue
        if item.get('exact') is not True:
            skipped['inexact_primary'] += 1
            continue
        shown[k] = bool(item.get('hints_shown'))
        scores = item.get('scores')
        if not isinstance(scores, dict):
            scores = {item.get('score_key') or 'overall@on': item['score']}
        for name, v in scores.items():
            if (k, name) in extra_seen:
                problems.append('DUPLICATE_EXTRA %s row %d' % (name, k))
            extra_seen.add((k, name))
            if not KEY.match(name):
                problems.append('BAD_KEY %s' % name)
            elif isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
                qs[k][name] = float(v)
            else:
                problems.append('NON_FINITE %s row %d' % (name, k))
    summary = {}
    if (run_dir / 'summary.json').is_file():
        summary = json.loads((run_dir / 'summary.json').read_text(encoding='utf-8'))
    return dict(qs=dict(qs), shown=shown, done=done, summary=summary, problems=problems, skipped=skipped)


def compare(name, score, reference, idx, labels, groups, iterations, smoke):
    y = [labels[i] for i in idx]
    a = auc(y, [score[i] for i in idx])
    out = dict(name=name, rows=len(idx), auc=None if a is None else round(a, 4),
               auc_ci=group_bootstrap([groups[i] for i in idx],
                                      lambda s: auc([labels[idx[j]] for j in s], [score[idx[j]] for j in s]), iterations),
               f1_at_rate_prev237={str(r): f1_at_rate(y, [score[i] for i in idx], r, TARGET_PREVALENCE) for r in RATES})
    if reference is not None and reference is not score:
        def delta(s):
            p = auc([labels[idx[j]] for j in s], [score[idx[j]] for j in s])
            q = auc([labels[idx[j]] for j in s], [reference[idx[j]] for j in s])
            return None if p is None or q is None else p - q
        ci = group_bootstrap([groups[i] for i in idx], delta, iterations)
        out['delta_auc_ci'] = ci
        out['promote'] = None if smoke else bool(ci and ci[0] > 0)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--input', type=Path, required=True)
    ap.add_argument('--run', type=Path, action='append', required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--reference', help='variant name run_index:key (default 0:<primary key of run 0>)')
    ap.add_argument('--group-regex', default=r'^([^:]+)')
    ap.add_argument('--iterations', type=int, default=1000)
    ap.add_argument('--min-rows', type=int, default=300)
    a = ap.parse_args(argv)
    ids, labels, digests = read_labelled(a.input)
    groups = groups_of(ids, a.group_regex)
    smoke = len(ids) < a.min_rows
    runs = [read_run(r, digests) for r in a.run]
    report = dict(rows=len(ids), positives=sum(labels), groups=len(set(groups)), smoke_only=smoke,
                  rule='promote only when the lower end of the grouped 95% CI of delta AUC > 0',
                  runs=[dict(path=str(p), problems=r['problems'], skipped=r['skipped'], coverage={k: sum(1 for v in r['qs'].values() if k in v)
                                                                              for k in sorted({k for v in r['qs'].values() for k in v})},
                             stage_primary=r['done'].get('primary'), stage_extras=r['done'].get('extras'),
                             total_wall_seconds=r['summary'].get('total_wall_seconds'),
                             stage_wall_seconds=r['summary'].get('stage_wall_seconds')) for p, r in zip(a.run, runs)])
    if any(r['problems'] for r in runs):
        report['error'] = 'input/schema checks failed; no comparison computed'
    else:
        variants = {}
        for n, r in enumerate(runs):
            for k in sorted({k for v in r['qs'].values() for k in v}):
                variants['%d:%s' % (n, k)] = {i: v[k] for i, v in r['qs'].items() if k in v}
        ref_name = a.reference or '0:%s' % (runs[0]['done'].get('keys') or ['overall@on'])[0]
        if ref_name not in variants:
            raise SystemExit('reference %s not scored' % ref_name)
        common = sorted(set.intersection(*[set(v) for v in variants.values()]))
        report['reference'], report['common_rows'] = ref_name, len(common)
        ref = variants[ref_name]
        report['variants'] = [compare(name, s, ref, common, labels, groups, a.iterations, smoke)
                              for name, s in variants.items()]
        info = []
        for n, r in enumerate(runs):
            keys = sorted({k for v in r['qs'].values() for k in v})
            if len(keys) < 2:
                continue
            rows_n = [i for i in common if all(k in r['qs'][i] for k in keys)]
            for mode in ('mean_z', 'max_z'):
                s = combine({i: r['qs'][i] for i in rows_n}, dict(aggregate=mode, aggregate_keys=keys))
                info.append(compare('%d:%s' % (n, mode), s, ref, rows_n, labels, groups, a.iterations, smoke))
            s = oof_logistic(keys, rows_n, r['qs'], groups, labels)
            if len(s) == len(rows_n):
                info.append(compare('%d:logistic_oof' % n, s, ref, rows_n, labels, groups, a.iterations, smoke))
            for q in QUESTIONS:
                on, off = '%s@on' % q, '%s@off' % q
                if on in keys and off in keys:
                    shown = [i for i in rows_n if r['shown'].get(i)]
                    if shown:
                        so = {i: r['qs'][i][off] for i in shown}
                        info.append(compare('%d:%s_on_vs_off(hints_shown)' % (n, q), {i: r['qs'][i][on] for i in shown}, so,
                                            shown, labels, groups, a.iterations, smoke))
        report['aggregates_info_only'] = info
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding='utf-8')
    for v in report.get('variants', []) + report.get('aggregates_info_only', []):
        print('%-34s n=%-5d AUC %s CI %s dAUC %s promote %s' % (v['name'], v['rows'], v['auc'], v['auc_ci'],
              v.get('delta_auc_ci'), v.get('promote')))
    if report.get('error'):
        print(report['error'], [r['problems'] for r in runs])
    return report


if __name__ == '__main__':
    main()
