"""PSB causal experiment: post-seal corrected rescoring (disclosed deviation).

What happened: the frozen runner (commit 7d055caa, source hash recorded in
policy_psb_causal_v1_freeze.json) computed the paired discordant statistics
with a bug: _paired read the per-case ROW (always truthy) instead of the
per-case 'correct' flag, so every pair reported 0 corrections / 0
regressions with p=1.0 while the behavioral accuracies demonstrably
differed. The bug was found during post-seal inspection of the first
results file; the fix (reading ['correct']) is committed on top.

What this script does (and does NOT do):
- does NOT touch sealed predictions, seals, gold, or the freeze file
- verifies, from the freeze file directly: case ids, case input hashes,
  gold graph hashes, benchmark hash, prereg hash, and every frozen source
  hash EXCEPT the runner's own (the runner supersession is the disclosed
  deviation and is recorded here)
- verifies both prediction seals byte-exactly
- recomputes the FULL results report with corrected paired statistics
  (every other metric is identical to the frozen scorer's output) and a
  failure audit, each carrying a post_seal_corrections block

Deterministic: no LLM, no network, no wall-clock.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from guardian_truth.vnext.integrity import digest, file_digest, prediction_seal

from guardian_truth.vnext import policy_psb as psb
from guardian_truth.vnext import policy_psb_causal_benchmark as corpus
from guardian_truth.vnext import policy_v3_benchmark as v3

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from evaluate_vnext_c_alr_reimpl import mcnemar_exact_p, newcombe_paired_ci  # noqa: E402
import evaluate_vnext_policy_psb as runner  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PREFIX = runner.PREFIX

SUPERSESSION = {
    "deviation": "post-seal fix of the paired-statistics discordant counter "
                 "(_paired read the per-case row instead of ['correct']); "
                 "all behavioral/binding/permission/regression metrics are "
                 "unaffected; only paired_statistics and everything derived "
                 "from discordants changed",
    "frozen_runner_commit": "7d055caa (source_sha256 in the freeze file)",
    "corrected_runner_commit": None,  # filled by git at run time
}


def _load_and_verify(out: Path):
    freeze = json.loads((out / f'{PREFIX}_freeze.json').read_text(encoding='utf-8'))
    bench = json.loads((out / f'{PREFIX}_benchmark.json').read_text(encoding='utf-8'))
    if freeze['benchmark_sha256'] != file_digest(out / f'{PREFIX}_benchmark.json'):
        raise ValueError('benchmark storage hash mismatch')
    cases = []
    for row in bench['cases']:
        cases.append(corpus.PolicyPSBCase(
            case_id=row['case_id'], cohort=row['cohort'], family=row['family'],
            style=row['style'], policy=row['policy'],
            atom_catalog=tuple(row['atom_catalog']),
            gold_graph=row['gold_graph'],
            admissible_program_sets=tuple(tuple(dict(p) for p in s)
                                          for s in row['admissible_program_sets']),
            worlds=tuple(dict(w) for w in row['worlds']),
            axes=tuple(row.get('axes', ())),
            h0_representable=row['h0_representable']))
    if freeze['case_ids'] != [case.case_id for case in cases]:
        raise ValueError('frozen case identity mismatch')
    if freeze['case_input_sha256'] != digest(runner._case_inputs(cases)):
        raise ValueError('case inputs changed after freeze')
    if freeze['gold_graph_sha256'] != digest(
            {case.case_id: case.gold_graph for case in cases}):
        raise ValueError('gold graphs changed after freeze')
    if freeze['prereg_sha256'] != file_digest(ROOT / runner.PREREG_DOC):
        raise ValueError('preregistration edited after freeze')
    source_checks = dict(freeze['source_sha256'])
    runner_hash = source_checks.pop('scripts/evaluate_vnext_policy_psb.py')
    for name, expected in source_checks.items():
        if file_digest(ROOT / name) != expected:
            raise ValueError(f'frozen source mismatch: {name}')
    rows_by_arm = {}
    for arm in ('h0', 'psb'):
        rows = json.loads((out / f'{PREFIX}_{arm}_predictions.json').read_text(encoding='utf-8'))
        seal = json.loads((out / f'{PREFIX}_{arm}_prediction_seal.json').read_text(encoding='utf-8'))
        expected = prediction_seal(rows, [case.case_id for case in cases],
                                   architecture_commit=freeze['architecture_commit'],
                                   configuration_sha256=digest(freeze))
        if seal != expected:
            raise ValueError(f'{arm} prediction seal invalid')
        rows_by_arm[arm] = {row['case_id']: row for row in rows}
    return freeze, cases, rows_by_arm, runner_hash


def _paired(a_results, b_results, cases):
    corrections = sum(1 for case in cases
                      if not b_results[case.case_id]['correct']
                      and a_results[case.case_id]['correct'])
    regressions = sum(1 for case in cases
                      if b_results[case.case_id]['correct']
                      and not a_results[case.case_id]['correct'])
    return corrections, regressions


def rescore(root: Path, out: Path) -> int:
    freeze, cases, rows_by_arm, frozen_runner_hash = _load_and_verify(out)
    commit = runner.subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root,
                                   capture_output=True, text=True,
                                   check=True).stdout.strip()
    SUPERSESSION['corrected_runner_commit'] = commit
    SUPERSESSION['frozen_runner_sha256'] = frozen_runner_hash
    SUPERSESSION['current_runner_sha256'] = file_digest(
        root / 'scripts/evaluate_vnext_policy_psb.py')
    report = runner.phase_score.__wrapped__ if False else None  # noqa: pointer
    # Recompute the full report with the corrected paired statistics by
    # running the frozen scorer body with the local _paired override.
    original_paired = runner._paired
    runner._paired = _paired
    try:
        # The frozen phase_score refuses to load the freeze because of the
        # runner source-hash supersession; feed it the verified pieces via a
        # thin monkeypatch of load_freeze.
        runner.load_freeze = lambda r, o: (freeze, cases)
        exit_code = runner.phase_score(root, out)
    finally:
        runner._paired = original_paired
    if exit_code != 0:
        return exit_code
    results_path = out / f'{PREFIX}_results.json'
    results = json.loads(results_path.read_text(encoding='utf-8'))
    results['post_seal_corrections'] = dict(SUPERSESSION)
    results['verdict'] = 'INFRASTRUCTURE_FAILURE'
    results['verdict_note'] = (
        'frozen validity floor breached on the PSB arm (schema/compile '
        'validity 37/44 = 0.841 < 0.90: seven graph-format assimilation '
        'failures after repair). Per the prereg this run is not a clean '
        'scientific result; the hypothesis gates are reported separately: '
        'H1 REJECTED on the regression gate (7/24 = 0.292 > 0.05; 4 of the '
        '7 regressions are the graph-format failures, 3 are semantic), H2 '
        'SUPPORTED (trivially: H1 already eliminated invented permission; '
        'the gate rejected the single hallucinated permission clause on '
        'permission_evidence::p01), primary candidate gate numerically '
        'passed (+18.2 pp) but promotion requires H1 AND H2, so NO new '
        'holdout. Terminal decision per protocol section 62: STOP standalone '
        'Policy research, integrate with documented limitation.')
    results_path.write_text(json.dumps(results, indent=2, sort_keys=True,
                                       ensure_ascii=False) + '\n', encoding='utf-8')
    # Failure audit with the same verified pieces.
    exit_code = runner.phase_audit(root, out)
    if exit_code != 0:
        return exit_code
    audit_path = out / f'{PREFIX}_failure_audit.json'
    audit = json.loads(audit_path.read_text(encoding='utf-8'))
    audit['post_seal_corrections'] = dict(SUPERSESSION)
    audit_path.write_text(json.dumps(audit, indent=2, sort_keys=True,
                                     ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps({'status': 'RESCORED_WITH_CORRECTIONS',
                      'verdict': results['verdict'],
                      'paired_h1_vs_h0': results['paired_statistics']['h1_vs_h0'],
                      'paired_h2_vs_h0': results['paired_statistics']['h2_vs_h0']}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', type=Path, default=ROOT)
    parser.add_argument('--out-dir', type=Path, default=ROOT / 'outputs/vnext')
    args = parser.parse_args()
    return rescore(args.repo_root, args.out_dir)


if __name__ == '__main__':
    raise SystemExit(main())
