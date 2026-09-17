"""Final artifact assembly for the session B real-valid cycle:
- outputs/vnext/real_valid_b/metrics.json (all stages, §31)
- outputs/vnext/real_valid_b/iterations.json (§29 machine-readable log)
- outputs/vnext/real_valid_b/cases.jsonl (§19 per-case audit, final stage)
- outputs/vnext/real_valid_b/premise_coverage.csv (final)
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / 'src'))
sys.path.insert(0, str(REPO / 'scripts'))

from real_valid_score import binary_of

BASE = REPO / 'outputs/vnext/real_valid_b'
GOLD_FRAME = pd.read_parquet(REPO / 'valid.parquet')
GOLD = {str(r['id']): int(r['label']) for _, r in GOLD_FRAME.iterrows()}
EXPL = {str(r['id']): (r['explanation'] if isinstance(r['explanation'], str) else '')
        for _, r in GOLD_FRAME.iterrows()}

STAGES = {
    'S0_baseline': 'R1_iter0/R1_progress.json',
    'S0_schemas_control': 'R1_control/R1_progress.json',
    'S1_catalog_conformance': 'R1/R1_progress.json',
    'S2_must_act_abstention': 'R1_fix2/R1_progress.json',
    'S3_final': 'R1_final/R1_progress.json',
    'S3_final_R2_T2off': 'R2_final/R2_progress.json',
}


def confusion(rows):
    tp = fp = fn = tn = 0
    for row in rows:
        predicted = binary_of(row)
        actual = GOLD[row['case_id']]
        if predicted == 1 and actual == 1: tp += 1
        elif predicted == 1 and actual == 0: fp += 1
        elif predicted == 0 and actual == 1: fn += 1
        else: tn += 1
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    statuses = Counter(row['core_status'] for row in rows)
    return {
        'TP': tp, 'FP': fp, 'FN': fn, 'TN': tn,
        'precision': round(p, 4), 'recall': round(r, 4),
        'f1': round(2 * p * r / (p + r), 4) if p + r else 0.0,
        'status_counts': dict(statuses),
        'PROVED_ERROR': statuses.get('PROVED_ERROR', 0),
        'PROVED_NO_ERROR': statuses.get('PROVED_NO_ERROR', 0),
        'UNRESOLVED': statuses.get('UNRESOLVED', 0) + statuses.get('EXECUTION_ERROR', 0),
        'INCONSISTENT': statuses.get('INCONSISTENT', 0),
        'certified_definitive': sum(1 for row in rows
                                    if row['core_status'] in ('PROVED_ERROR', 'PROVED_NO_ERROR')
                                    and row.get('certificate_valid')),
        'false_certified_ERROR': sum(1 for row in rows if row['core_status'] == 'PROVED_ERROR'
                                     and GOLD[row['case_id']] == 0 and row.get('certificate_valid')),
        'false_certified_NO_ERROR': sum(1 for row in rows if row['core_status'] == 'PROVED_NO_ERROR'
                                        and GOLD[row['case_id']] == 1 and row.get('certificate_valid')),
        'uncertified_definitive': sum(1 for row in rows
                                      if row['core_status'] in ('PROVED_ERROR', 'PROVED_NO_ERROR')
                                      and not row.get('certificate_valid')),
        'goal_contracts_available': sum(1 for row in rows if row.get('goal_contract_count', 0) > 0),
    }


def main():
    metrics = {'note': 'DEVELOPMENT RESULT on viewed valid.parquet (46 cases); '
                       'not a generalization or hidden-test claim',
               'provider': 'mistral/ministral-14b-latest',
               'architecture': 'B4h-sound-v2 @ 315bee3 + session A iteration-1 (goal repair) '
                               '+ session B iterations 1-2 (catalog conformance, REP-08)'}
    rows_by_stage = {}
    for stage, rel in STAGES.items():
        path = BASE / rel
        if not path.exists():
            continue
        rows = json.loads(path.read_text(encoding='utf-8'))
        rows_by_stage[stage] = rows
        metrics[stage] = confusion(rows)
    (BASE / 'metrics.json').write_text(json.dumps(metrics, ensure_ascii=False, indent=1),
                                       encoding='utf-8')

    # §29 iterations machine log
    iterations = [
        {'iteration': 0, 'commit': '315bee3', 'description': 'frozen B4h-sound-v2 baseline (session B adapter)',
         'metrics': metrics.get('S0_baseline')},
        {'iteration': '0c', 'commit': '574c6d9', 'description': 'adapter control: typed schema trees (no new proof axis)',
         'metrics': metrics.get('S0_schemas_control')},
        {'iteration': 1, 'root_cause': 'no deterministic catalog/argument-schema proof path (INVALID_TOOL_NAME, '
                                       'INVALID_ARGUMENT_SCHEMA families; directive §14 priorities 2-3)',
         'hypothesis': 'a deterministic catalog-conformance axis over RESPONSE calls (catalog membership + required '
                       'fields incl. nested array items + enum values) certifies these violations with zero T1 and '
                       'zero LLM, flag-gated default OFF',
         'changed_files': ['src/guardian_truth/vnext/proof_records.py (2 AtomKinds)',
                           'src/guardian_truth/vnext/tools.py (ContractRegistry.schemas)',
                           'src/guardian_truth/vnext/e2e/catalog_conformance_v1.py (new)',
                           'src/guardian_truth/vnext/e2e/world_integration_v1.py (prover branch)',
                           'src/guardian_truth/vnext/e2e/core_v1.py (flag + wiring)',
                           'src/guardian_truth/vnext/e2e/certificate_context_v1.py (checker branch + registry hash)',
                           'scripts/real_valid_run.py'],
         'tests': ['tests/e2e/test_catalog_conformance.py (14 tests incl. rename-invariance, '
                   'paired fix-the-condition metamorphic, label/id independence)'],
         'metrics_before': metrics.get('S0_schemas_control'), 'metrics_after': metrics.get('S1_catalog_conformance'),
         'corrections': ['airline__23::t10 UNRESOLVED->PROVED_ERROR (schema: payment_methods items lack payment_id)',
                         'banking_knowledge__task_083::t10 UNRESOLVED->PROVED_ERROR (non-catalog tool)'],
         'regressions': [],
         'decision': 'KEEP'},
        {'iteration': 2, 'root_cause': 'absence-only "must act THIS turn" obligations (policy/goal REQUIRE_CALL, '
                                       'GOAL_CALL) manufactured certified false-ERRORs on legitimate '
                                       'information-gathering turns (REP-08: must-act existential semantics are '
                                       'outside the V1 program space)',
         'hypothesis': 'converting absence-scoped FALSE on non-claim action-existential obligations to UNKNOWN '
                       '(flag must_act_abstention in E2ESemantics, default OFF) removes the false-certified ERROR '
                       'family while preserving claim-path fabricated-action proofs',
         'changed_files': ['src/guardian_truth/vnext/e2e/e2e_types_v1.py (E2ESemantics.must_act_abstention)',
                           'src/guardian_truth/vnext/e2e/world_integration_v1.py (solve_world gate)',
                           'scripts/real_valid_run.py'],
         'tests': ['tests/e2e/test_must_act_abstention.py (5 tests: gate on/off, claim exemption, '
                   'prohibition unaffected, positive-call satisfaction)'],
         'metrics_before': metrics.get('S1_catalog_conformance'), 'metrics_after': metrics.get('S2_must_act_abstention'),
         'corrections': ['airline__47::t1 false-certified ERROR removed (policy absence witness)',
                         'banking_knowledge__task_033::t2 false-certified ERROR removed (goal absence witness)'],
         'regressions': ['banking_knowledge__task_051::t15 TP->UNRESOLVED: its violation was covered in the '
                         'binding-alternative worlds ONLY by the absence witness; the REP-08 gate correctly '
                         'abstains there (soundness over F1, directive §27)'],
         'decision': 'KEEP'},
        {'iteration': '3-adopted', 'root_cause': 'goal_conservative single-shot schema fragility on real multi-intent '
                                                 'user requests (session A iteration 1, KEEP)',
         'hypothesis': 'adopting session A\'s goal repair (one machine-validation re-ask, opt-in flag) in the '
                       'session B line raises goal availability without new production code',
         'changed_files': ['scripts/real_valid_run.py (goal_format_repair=True)'],
         'tests': ['tests/e2e/test_goal_conservative_repair.py (session A, 11 tests)'],
         'metrics_before': metrics.get('S2_must_act_abstention'), 'metrics_after': metrics.get('S3_final'),
         'corrections': ['airline__44::t22 UNRESOLVED->PROVED_ERROR',
                         'telecom__mobile_data_issue...::t6 UNRESOLVED->PROVED_ERROR'],
         'regressions': [],
         'decision': 'KEEP (adoption of session A iteration 1)'},
    ]
    (BASE / 'iterations.json').write_text(json.dumps(iterations, ensure_ascii=False, indent=1),
                                          encoding='utf-8')

    # §19 cases.jsonl — final stage merged with earlier-stage context
    envelope = json.loads((BASE / 'dataset_envelope.json').read_text(encoding='utf-8'))
    env_by_id = {case['id']: case for case in envelope['cases']}
    final_rows = rows_by_stage['S3_final']
    with open(BASE / 'cases.jsonl', 'w', encoding='utf-8') as handle:
        for row in sorted(final_rows, key=lambda item: item['case_id']):
            case_id = row['case_id']
            env = env_by_id[case_id]
            record = {
                'id': case_id,
                'domain_posthoc': env['domain'],
                'gold_label_posthoc': GOLD[case_id],
                'gold_explanation_posthoc': EXPL[case_id][:500],
                'input': row.get('input', {}),
                'environment': row.get('environment', {}),
                'target': row.get('target', {}),
                'required_premises': row.get('required_premises', []),
                't2_premises': row.get('t2_premises', []),
                'stage_S0': {'core_status': next((r['core_status'] for r in rows_by_stage['S0_baseline']
                                                  if r['case_id'] == case_id), None)},
                'stage_S1': {'core_status': next((r['core_status'] for r in rows_by_stage['S1_catalog_conformance']
                                                  if r['case_id'] == case_id), None)},
                'stage_S2': {'core_status': next((r['core_status'] for r in rows_by_stage['S2_must_act_abstention']
                                                  if r['case_id'] == case_id), None)},
                'S3_final': {'core_status': row['core_status'], 'binary': binary_of(row),
                             'certificate_valid': row.get('certificate_valid'),
                             'frontend_failures': row.get('frontend_failures', []),
                             'component_summary': row.get('component_summary', {}),
                             'diagnostics': row.get('diagnostics', {}),
                             'false_witnesses': row.get('false_witnesses', [])},
                'manual_t1_required': bool(not row.get('trusted_effect_count')),
                'missing_information': (row.get('diagnostics') or {}).get('missing_evidence', [])[:8],
                'proof': {
                    'core_status': row['core_status'],
                    'certificate_valid': row.get('certificate_valid'),
                    'false_witnesses': row.get('false_witnesses', []),
                    'unknown_reasons': (row.get('diagnostics') or {}).get('missing_evidence', [])[:8],
                },
            }
            handle.write(json.dumps(record, ensure_ascii=False) + '\n')

    # premise coverage (final)
    with open(BASE / 'premise_coverage.csv', 'w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle)
        writer.writerow(['id', 'verdict_final', 'works_without_T1', 'used_T2',
                         'trusted_effects', 't2_premise_count', 'classification'])
        for row in final_rows:
            verdict = row['core_status']
            used_t2 = bool(row.get('t2_premises'))
            if verdict == 'PROVED_ERROR':
                witness_catalog = any('catalog' in w for w in row.get('false_witnesses', []))
                classification = ('STRUCTURAL_CATALOG' if witness_catalog
                                 else ('WORKS_WITHOUT_T1' if not used_t2 else 'PROMPT_DERIVED_T2'))
            elif verdict == 'PROVED_NO_ERROR':
                classification = 'NO_ERROR_CERTIFIED'
            else:
                classification = 'UNRESOLVED'
            writer.writerow([row['case_id'], verdict, int(verdict == 'PROVED_ERROR' and not used_t2),
                             int(used_t2), row.get('trusted_effect_count', 0),
                             len(row.get('t2_premises') or []), classification])

    print(json.dumps({stage: {'f1': metrics[stage]['f1'], 'TP': metrics[stage]['TP'],
                              'FP': metrics[stage]['FP'],
                              'falseCertERR': metrics[stage]['false_certified_ERROR']}
                      for stage in metrics if stage.startswith('S')}, indent=1))


if __name__ == '__main__':
    main()
