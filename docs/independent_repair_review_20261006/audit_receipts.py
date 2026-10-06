"""Read-only independent recomputation; no inference and no historical writes.
Run from repository root: python -X utf8 docs/independent_repair_review_20261006/audit_receipts.py --output NEW.json
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import socket
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]

def forbidden(*args, **kwargs):
    raise RuntimeError('AUDIT_NETWORK_FORBIDDEN')

socket.create_connection = forbidden
socket.socket.connect = forbidden
socket.socket.connect_ex = forbidden

from experiments.universal_repair.run import inputs
from experiments.universal_repair.score import gold_for, arm_records
from experiments.universal_repair.funnel import stage
from guardian_truth.repair.v5 import decide

SETS = {'valid46': (1, 2, 3), 'lb_long': (1,), 'lb2_long': (1,),
        'lb3_long': (1, 2), 'ext_tau2': (1, 2, 3), 'hold_tau2h': (1, 2, 3)}
ARMS = ('V4r', 'R_fix', 'R_comb')

def compute(pred, gold):
    assert set(gold) <= set(pred), 'missing scored rows'
    counts = Counter()
    for rid, g in gold.items():
        p = bool(pred[rid][0])
        y = bool(g['label'])
        counts['tp' if p and y else 'fp' if p else 'fn' if y else 'tn'] += 1
    out = {k: counts[k] for k in ('tp', 'fp', 'fn', 'tn')}
    out['f1'] = round(2 * out['tp'] / (2 * out['tp'] + out['fp'] + out['fn']), 3) if out['tp'] else 0
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', required=True, type=Path)
    args = ap.parse_args()
    assert not args.output.exists(), 'refusing overwrite'
    report = {'scope': 'stored-run decision replay, not new inference or provider cache authentication',
              'network_blocked': True, 'sets': {}, 'source_sha256': {}}
    frozen = json.loads((ROOT / 'outputs/universal_repair/phase4/report.json').read_text(encoding='utf-8'))
    mismatches, fn_stages, no_trigger_a, schema_losses = [], Counter(), Counter(), []
    confirm_events = 0
    row_executions = 0
    cause_text_changes = []
    for name, reps in SETS.items():
        gold = gold_for(name)
        expected = {r['id'] for r in inputs(name)}
        assert len(expected) == len(inputs(name)), 'duplicate input ids'
        for rep in reps:
            sr = f'{name}#{rep}'
            preds = {}
            result = {'expected_rows': len(expected), 'scored_rows': len(gold), 'arms': {}}
            row_executions += len(expected)
            for arm in ARMS:
                mode = 'offline' if arm == 'V4r' else 'live'
                try:
                    recs, ledger = arm_records(name, rep, arm, mode)
                except FileNotFoundError:
                    assert arm == 'V4r'
                    recs, ledger = arm_records(name, rep, arm, 'live')
                assert set(recs) == expected, 'unexpected row set'
                pred = {rid: decide(rec) for rid, rec in recs.items()}
                preds[arm] = pred
                m = compute(pred, gold)
                result['arms'][arm] = m
                historical = frozen['sets'][sr][arm]
                for k in ('tp', 'fp', 'fn', 'f1'):
                    if m[k] != historical[k]:
                        mismatches.append((sr, arm, k, m[k], historical[k]))
                if arm == 'R_fix':
                    for rid, rec in recs.items():
                        confirm_events += int('CB' in (rec.get('components') or {}))
                        if rid not in gold or gold[rid]['label'] != 1 or pred[rid][0]:
                            continue
                        st = stage(rec)
                        fn_stages[st] += 1
                        if st == 'NO_TRIGGER':
                            no_trigger_a[(rec.get('A_adm2') or {}).get('decision') or 'NONE'] += 1
                        if st == 'NO_CANDIDATE':
                            for component, c in (rec.get('components') or {}).items():
                                values = [c.get('admission')] + list(c.get('batch_admission') or [])
                                if any('INVALID_JSON' in str(v) for v in values):
                                    schema_losses.append({'set': name, 'rep': rep, 'id': rid,
                                                          'component': component, 'admissions': values})
            result['binary_flips'] = {arm: sorted(rid for rid in expected if preds[arm][rid][0] != preds['V4r'][rid][0])
                                      for arm in ARMS[1:]}
            for rid in expected:
                if preds['R_fix'][rid][0] and preds['V4r'][rid][0] and preds['R_fix'][rid][1] != preds['V4r'][rid][1]:
                    cause_text_changes.append({'set': name, 'rep': rep, 'id': rid,
                                               'before': preds['V4r'][rid][1], 'after': preds['R_fix'][rid][1]})
            report['sets'][sr] = result
    report.update(matrix_mismatches=mismatches, row_executions=row_executions,
                  fn_stages=dict(fn_stages), no_trigger_A_decisions=dict(no_trigger_a),
                  schema_failures_hidden_in_no_candidate=schema_losses,
                  R_fix_CB_component_rows=confirm_events, R_fix_positive_accusation_changes=cause_text_changes)
    assert not mismatches
    judges = {}
    for line in (ROOT / 'outputs/universal_repair/cause/judgements_a0.jsonl').read_text(encoding='utf-8').splitlines():
        rec = json.loads(line)
        key = (rec['set'], rec['id'], rec['acc_text'])
        assert key not in judges, 'duplicate successful judge key'
        judges[key] = rec
    contradictions = []
    for rec in judges.values():
        j = rec['judgement']
        cat = j['category']
        bad = []
        if cat in ('supported_correct_core', 'supported_core_with_unsupported_extra', 'alternative_supported_cause') and j.get('accusation_supported') != 'yes':
            bad.append('supported category without supported core')
        if cat in ('supported_correct_core', 'supported_core_with_unsupported_extra') and j.get('core_matches_gold') != 'yes':
            bad.append('gold-matching category without gold match')
        if cat == 'unsupported' and j.get('accusation_supported') == 'yes':
            bad.append('unsupported category with supported core')
        if bad:
            contradictions.append(dict(set=rec['set'], rep=rec['rep'], id=rec['id'], issues=bad, judgement=j))
    report['judge_unique'] = len(judges)
    report['judge_contract_contradictions'] = contradictions
    cause_sensitivity = {}
    for arm in ARMS:
        ct = Counter()
        for name, reps in SETS.items():
            g = gold_for(name)
            for rep in reps:
                try:
                    recs, _ = arm_records(name, rep, arm, 'offline' if arm == 'V4r' else 'live')
                except FileNotFoundError:
                    recs, _ = arm_records(name, rep, arm, 'live')
                for rid, rec in recs.items():
                    p, acc = decide(rec)
                    if not p or rid not in g or g[rid]['label'] != 1:
                        continue
                    ct['tp'] += 1
                    j = judges[(name, rid, acc.get('text') or '')]['judgement']
                    if j['category'] in ('supported_correct_core', 'supported_core_with_unsupported_extra'):
                        ct['published_correct_category'] += 1
                        if j.get('accusation_supported') != 'yes':
                            ct['correct_category_but_core_not_yes'] += 1
                        if j.get('core_matches_gold') != 'yes':
                            ct['correct_category_but_gold_match_not_yes'] += 1
        cause_sensitivity[arm] = dict(ct)
    report['cause_contract_sensitivity_not_truth_rescore'] = cause_sensitivity
    report['valid_judge_categories'] = dict(Counter(rec['judgement']['category'] for rec in judges.values() if rec['set'] == 'valid46'))
    import pandas as pd
    frame = pd.read_parquet(ROOT / 'valid.parquet')
    report['valid_explanation_nonempty'] = sum(isinstance(v, str) and bool(v.strip()) for v in frame.explanation)
    report['valid_gold_for_drops_explanation'] = all(set(g) == {'label'} for g in gold_for('valid46').values())
    hold = ROOT / 'outputs/universal_repair/holdout/tau2h'
    g = gold_for('hold_tau2h')
    manifest = json.loads((hold / 'MANIFEST.json').read_text(encoding='utf-8'))
    report['holdout'] = dict(labels=dict(Counter(v['label'] for v in g.values())),
                            documented_drop_entries=len(manifest['drops']), actual_excluded=sum(manifest['excluded'].values()),
                            retained_drop_entries=[rid for rid, v in g.items() if v['case'] in manifest['drops']],
                            all_positive_f1=2 * 41 / (2 * 41 + 10),
                            source_gold_conflict_candidates=['hold_air_057', 'hold_air_020', 'hold_ret_002'])
    report['holdout']['manifest_hash_match'] = {
        n: hashlib.sha256((hold / n).read_bytes()).hexdigest() == manifest[k]
        for n, k in [('inputs.jsonl', 'sha256_inputs'), ('GOLD_frozen.json', 'sha256_gold')]}
    for path in [ROOT / 'valid.parquet', hold / 'inputs.jsonl', hold / 'GOLD_frozen.json', hold / 'MANIFEST.json']:
        report['source_sha256'][str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8', newline='\n') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print(json.dumps({k: report[k] for k in ['row_executions', 'matrix_mismatches', 'fn_stages', 'no_trigger_A_decisions', 'R_fix_CB_component_rows', 'judge_unique', 'valid_explanation_nonempty', 'holdout']}, ensure_ascii=False))
    print('judge contradictions', len(contradictions), 'schema losses', len(schema_losses))

if __name__ == '__main__':
    main()
