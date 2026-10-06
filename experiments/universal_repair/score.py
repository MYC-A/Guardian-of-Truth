"""Universal-repair scorer: validated records only (records.load), per set/rep/arm TP/FP/FN/F1, flips, parity."""
import json
from pathlib import Path

from guardian_truth.repair import records
from guardian_truth.repair.v5 import decide
from guardian_truth.verification.v4 import decide_v4
from .run import ROOT, OUT, inputs

SETS = {'valid46': (1,), 'lb_long': (1,), 'lb2_long': (1,), 'lb3_long': (1, 2), 'ext_tau2': (1, 2, 3)}
V4TAG = {'ext_tau2': '_v4'}


def gold_for(name):
    if name == 'valid46':
        import pandas as pd
        return {r.id: dict(label=int(r.label)) for r in pd.read_parquet(ROOT / 'valid.parquet').itertuples()}
    if name in ('ext_tau2', 'ext_tau2v2', 'ext_tau2v2_strict'):
        d = {'ext_tau2': 'tau2v2', 'ext_tau2v2': 'tau2v2', 'ext_tau2v2_strict': 'tau2v2_strict'}[name]
        return json.loads((ROOT / 'outputs/verification_v4/external' / d / 'GOLD_eval_only.json').read_text(encoding='utf-8'))
    if name.startswith('hold_'):
        return json.loads((OUT / 'holdout' / name[5:] / 'GOLD_frozen.json').read_text(encoding='utf-8'))
    d = {'lb_long': 'lockbox', 'lb2_long': 'lockbox2', 'lb3_long': 'lockbox3'}[name]
    return json.loads((ROOT / 'outputs/verification_v2' / d / 'long/GOLD_eval_only.json').read_text(encoding='utf-8'))


def metrics(pred, gold):
    pred = {i: p for i, p in pred.items() if i in gold}
    tp = sum(bool(p) and gold[i]['label'] == 1 for i, p in pred.items())
    fp = sum(bool(p) and gold[i]['label'] == 0 for i, p in pred.items())
    fn = sum(not p and gold[i]['label'] == 1 for i, p in pred.items())
    return dict(tp=tp, fp=fp, fn=fn, f1=round(2 * tp / (2 * tp + fp + fn), 3) if tp else 0.0)


def v4_records(name, rep):
    tag = V4TAG.get(name, '_v4dev3')
    ids = [r['id'] for r in inputs(name)]
    recs, _ = records.load(ROOT / 'outputs/verification_v2/runs' / name / f'rep{rep}{tag}.jsonl', ids)
    return recs


def arm_records(name, rep, arm, mode='offline', cb=False):
    ids = [r['id'] for r in inputs(name)]
    return records.load(OUT / 'runs' / name / f'rep{rep}_{arm}{"_cb" if cb else ""}_{mode}.jsonl', ids)


def parity(name, rep):
    """V4r (flags=∅) must reproduce stored V4 decisions and accusation targets exactly."""
    old = v4_records(name, rep)
    new, rep_ = arm_records(name, rep, 'V4r')
    diff = []
    for i in old:
        a, b = decide_v4(old[i])['V4'], decide(new[i])
        if a[0] != b[0] or (a[1] or {}).get('target_id') != (b[1] or {}).get('target_id') or (a[1] or {}).get('origin') != (b[1] or {}).get('origin'):
            diff.append((i, a[0], b[0], (a[1] or {}).get('origin'), (b[1] or {}).get('origin')))
    return diff
