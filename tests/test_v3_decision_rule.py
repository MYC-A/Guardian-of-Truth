import csv
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from v3_decision_rule import em_prior, metrics, quota
from scipy.special import logit


def test_synthetic_em_recovers_shifted_prior():
    # Analytic Gaussian class densities, so calibrated LR is known exactly.
    rng = np.random.default_rng(20261019)
    y = rng.random(50000) < .20
    x = rng.normal(np.where(y, 2., -2.), 1.)
    # log N(x;2,1)/N(x;-2,1) = 4*x.
    prior, _, _, converged = em_prior(4 * x, .65)
    assert converged and abs(prior - .20) < .02


def test_native_r0_matches_published():
    path = Path(__file__).resolve().parents[1] / 'docs/judge_20261013/v3_A_evidence/score_rows.csv'
    if not path.exists():
        # Same frozen published raw evidence, before the new result directory exists.
        path = Path('A:/Guardian-submissions/judge-gpu-a6000-20261018/runs/regression_r1/rows.csv')
    with path.open(encoding='utf8', newline='') as f:
        rows = list(csv.DictReader(f))
    y = np.array([int(r['label']) for r in rows])
    s = np.array([float(r['score']) for r in rows]); h = np.array([bool(r['hard']) for r in rows])
    assert len(y) == 397
    assert abs(metrics(y, quota(s, h))['f1'] - .7512437810945274) < 1e-12


def test_hard_rows_consume_quota_and_ties_use_order():
    assert quota(np.zeros(5), np.array([False, False, False, False, True])).tolist() == [True, False, False, False, True]
