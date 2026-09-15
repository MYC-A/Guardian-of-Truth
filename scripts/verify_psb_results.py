"""Independent post-hoc revalidation of the sealed PSB causal artifacts.

Recomputes, from the sealed prediction files and the frozen benchmark alone:
seal validity, freeze-content hashes, per-arm behavioral accuracies,
invented-permission counters, validity, the frozen gate arithmetic and the
terminal verdict. No LLM, no network. Exit 0 only if every check matches
the published results file.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))

from guardian_truth.vnext.integrity import digest, file_digest, prediction_seal  # noqa: E402
from guardian_truth.vnext import policy_psb as psb  # noqa: E402
from guardian_truth.vnext import policy_psb_causal_benchmark as corpus  # noqa: E402
from guardian_truth.vnext import policy_v3_benchmark as v3  # noqa: E402

OUT = ROOT / 'outputs/vnext'
PREFIX = 'policy_psb_causal_v1'


def main() -> int:
    freeze = json.loads((OUT / f'{PREFIX}_freeze.json').read_text(encoding='utf-8'))
    bench = json.loads((OUT / f'{PREFIX}_benchmark.json').read_text(encoding='utf-8'))
    results = json.loads((OUT / f'{PREFIX}_results.json').read_text(encoding='utf-8'))
    cases = []
    for row in bench['cases']:
        cases.append(corpus.PolicyPSBCase(
            case_id=row['case_id'], cohort=row['cohort'], family=row['family'],
            style=row['style'], policy=row['policy'],
            atom_catalog=tuple(row['atom_catalog']), gold_graph=row['gold_graph'],
            admissible_program_sets=tuple(tuple(dict(p) for p in s)
                                          for s in row['admissible_program_sets']),
            worlds=tuple(dict(w) for w in row['worlds']),
            axes=tuple(row.get('axes', ())),
            h0_representable=row['h0_representable']))
    checks = []
    checks.append(('benchmark_hash', freeze['benchmark_sha256']
                   == file_digest(OUT / f'{PREFIX}_benchmark.json')))
    checks.append(('gold_graph_hash', freeze['gold_graph_sha256'] == digest(
        {case.case_id: case.gold_graph for case in cases})))
    checks.append(('case_ids', freeze['case_ids'] == [c.case_id for c in cases]))
    rows_by_arm = {}
    for arm in ('h0', 'psb'):
        rows = json.loads((OUT / f'{PREFIX}_{arm}_predictions.json').read_text(encoding='utf-8'))
        seal = json.loads((OUT / f'{PREFIX}_{arm}_prediction_seal.json').read_text(encoding='utf-8'))
        expected = prediction_seal(rows, [c.case_id for c in cases],
                                   architecture_commit=freeze['architecture_commit'],
                                   configuration_sha256=digest(freeze))
        checks.append((f'{arm}_seal', seal == expected))
        checks.append((f'{arm}_seal_gold_joined_false', seal['gold_joined'] is False))
        rows_by_arm[arm] = {row['case_id']: row for row in rows}

    def arm_outcomes(arm):
        correct_n, valid_n, invented = 0, 0, 0
        for case in cases:
            row = rows_by_arm['h0' if arm == 'h0' else 'psb'][case.case_id]
            pred = row['prediction']
            programs = None
            if pred is not None:
                try:
                    if arm == 'h0':
                        programs = [v3.compile_v3_structure(dict(pred))]
                    else:
                        programs, _ = psb.compile_psb_graph(
                            dict(pred), permission_gate=(arm == 'h2'),
                            policy_text=case.policy)
                except (ValueError, TypeError):
                    programs = None
            if programs is not None:
                valid_n += 1
                ok, per_world = psb.score_program_set(
                    programs, case.worlds, case.admissible_program_sets)
                if ok:
                    correct_n += 1
                if any(w.get('verdict') == 'PERMITTED'
                       and 'PERMITTED' not in w.get('acceptable', [])
                       for w in per_world):
                    invented += 1
        return correct_n, valid_n, invented

    for arm in ('h0', 'h1', 'h2'):
        correct_n, valid_n, invented = arm_outcomes(arm)
        published = results['primary_metric'][arm]
        checks.append((f'{arm}_correct', correct_n == published['correct']))
        checks.append((f'{arm}_validity', valid_n == round(results['validity'][arm] * 44)))
        checks.append((f'{arm}_invented', invented
                       == results['permission'][arm]['invented_permission_cases']))
        print(f'{arm}: correct={correct_n}/44 valid={valid_n}/44 invented={invented}')
    h0c = results['primary_metric']['h0']['correct']
    h1c = results['primary_metric']['h1']['correct']
    h2c = results['primary_metric']['h2']['correct']
    checks.append(('h1_delta_ge_10pp', (h1c - h0c) / 44 >= 0.10))
    checks.append(('regression_rate',
                   results['regressions']['h0_correct_to_h1_wrong']['rate'] == round(7 / 24, 4)))
    checks.append(('verdict_field', results['verdict'] == 'INFRASTRUCTURE_FAILURE'))
    checks.append(('h1_supported_false', results['h1_hypothesis_supported'] is False))
    checks.append(('h2_supported_true', results['h2_hypothesis_supported'] is True))
    failed = [name for name, ok in checks if not ok]
    print(json.dumps({'status': 'REVALIDATED' if not failed else 'MISMATCH',
                      'checks': len(checks), 'failed': failed}, indent=1))
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
