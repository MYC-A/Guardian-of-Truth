"""Fresh holdout2 for v6 (built and frozen BEFORE any v6 run on it). Same Amendment-2 gold method as tau2h
(experiments/universal_repair/holdout.py): F1/F2 format causes by fixed regex + the tau2 oracle's wrong/unauthorised write,
manual review may only DROP oracle causes. Disjoint at TASK level from the 70 frozen external rows AND from tau2h.
Larger negative strata than tau2h (specificity was the weak, low-n metric there).
  python -m experiments.guardian_v6.holdout2 review|freeze"""
import argparse, hashlib, json
from collections import Counter
from experiments.verification_v4.external import build as B
from experiments.universal_repair import holdout as H1

ROOT = H1.ROOT
OUTD = ROOT / 'outputs/guardian_v6/holdout2'
TAU2H = H1.OUTD
SEED = 'guardian-v6-holdout2-20261007'
QUOTA = {'err': 45, 'gold_write': 30, 'multi_read': 20}
DROPS = {'54b86d9af38a': 'user explicitly chose/confirmed these values in the visible transcript; oracle disagreement stems from hidden user instructions, not from a checkable policy/source violation (same decision as tau2h review)',
    '581eeb9210d8': 'user explicitly chose/confirmed these values in the visible transcript; oracle disagreement stems from hidden user instructions, not from a checkable policy/source violation (same decision as tau2h review)',
    'd7c57fb2c5c1': 'user explicitly chose/confirmed these values in the visible transcript; oracle disagreement stems from hidden user instructions, not from a checkable policy/source violation (same decision as tau2h review)',
    '2e27ca62cf53': 'only a permutation of item_ids; not an error',
    '47a7fbadbc5d': 'user explicitly chose/confirmed these values in the visible transcript; oracle disagreement stems from hidden user instructions, not from a checkable policy/source violation (user dictated the cancel reason)',
    'b2c6e6e742b9': 'user explicitly chose/confirmed these values in the visible transcript; oracle disagreement stems from hidden user instructions, not from a checkable policy/source violation (user agreed to the 1GB amount)',
    '621ba9abe590': 'user explicitly chose/confirmed these values in the visible transcript; oracle disagreement stems from hidden user instructions, not from a checkable policy/source violation (user confirmed the exact flight HAT175)'}          # filled by the manual review (DROP only, with reason), before freeze


def candidates():
    pids, tasks, pool = H1.frozen_tasks()
    g1 = json.loads((TAU2H / 'MANIFEST.json').read_text(encoding='utf-8'))
    used = {c['pool_id'] for c in g1['cases']}
    tasks |= {(x['domain'], x['task_id']) for x in pool if x['pool_id'] in used}
    order = sorted(pool, key=lambda x: hashlib.sha256((SEED + x['pool_id']).encode()).hexdigest())
    chosen, per = {k: [] for k in QUOTA}, set()
    for x in order:
        k = 'err' if x['label'] == 1 else x['family']
        if k not in QUOTA or x['pool_id'] in pids or x['pool_id'] in used or (x['domain'], x['task_id']) in tasks | per:
            continue
        if x['pool_id'] in B.DROPS or B.rule_drop(x) or len(chosen[k]) >= QUOTA[k]:
            continue
        chosen[k].append(x); per.add((x['domain'], x['task_id']))
    return [y for k in QUOTA for y in chosen[k]]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('stage', choices=['review', 'freeze', 'stats'])
    a = ap.parse_args()
    if a.stage == 'stats':
        c = candidates(); print(len(c), Counter((x['domain'], x['label'], x['family']) for x in c)); return
    if a.stage == 'review':
        B.review_view([x for x in candidates() if x['label'] == 1], n_err=10 ** 6); return
    H1.OUTD, H1.DROPS, H1.candidates, H1.SEED = OUTD, DROPS, candidates, SEED
    H1.freeze()


if __name__ == '__main__':
    main()
