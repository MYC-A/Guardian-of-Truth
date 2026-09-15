"""Independent post-hoc revalidation of the sealed POLICY_FINAL_CYCLE results.

Re-derives the headline numbers from the sealed artifacts alone (freeze,
benchmark, four prediction seals, results) via a code path independent of the
scorer's helpers where practical. Deterministic; no network; no LLM.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from guardian_truth.vnext import policy_v3_benchmark as v3
from guardian_truth.vnext import policy_psb as psb
from guardian_truth.vnext import policy_grs as grs
from guardian_truth.vnext import policy_grs_emission as em
from guardian_truth.vnext.integrity import digest, file_digest, prediction_seal

OUT = ROOT / 'outputs' / 'vnext'
PREFIX = 'policy_final_holdout_v1'
CHECKS: list[tuple[str, bool]] = []


def check(name, ok):
    CHECKS.append((name, bool(ok)))


def main() -> int:
    freeze = json.loads((OUT / f'{PREFIX}_freeze.json').read_text(encoding='utf-8'))
    bench = json.loads((OUT / f'{PREFIX}_benchmark.json').read_text(encoding='utf-8'))
    results = json.loads((OUT / f'{PREFIX}_results.json').read_text(encoding='utf-8'))
    audit = json.loads((OUT / f'{PREFIX}_failure_audit.json').read_text(encoding='utf-8'))

    # 1. storage + identity
    check('benchmark hash', freeze['benchmark_sha256']
          == file_digest(OUT / f'{PREFIX}_benchmark.json'))
    check('prereg hash', freeze['prereg_sha256']
          == file_digest(ROOT / freeze['prereg']))
    check('gold frozen before predictions',
          freeze['gold_frozen_before_predictions'] is True
          and freeze['gold_joined'] is False)
    rows = bench['cases']
    check('case count 100', len(rows) == 100)
    check('case ids', [r['case_id'] for r in rows] == freeze['case_ids'])

    # 2. seals
    arms = {}
    for arm in ('h0', 'psb', 'ground', 'synth'):
        rows_arm = json.loads((OUT / f'{PREFIX}_{arm}_predictions.json')
                              .read_text(encoding='utf-8'))
        seal = json.loads((OUT / f'{PREFIX}_{arm}_prediction_seal.json')
                          .read_text(encoding='utf-8'))
        expected = prediction_seal(rows_arm, freeze['case_ids'],
                                   architecture_commit=freeze['architecture_commit'],
                                   configuration_sha256=digest(freeze))
        check(f'{arm} seal', seal == expected)
        check(f'{arm} gold not joined at seal', seal['gold_joined'] is False)
        arms[arm] = {r['case_id']: r for r in rows_arm}
    check('arm ok counts',
          (sum(r['status'].startswith('ok') for r in arms['h0'].values()),
           sum(r['status'].startswith('ok') for r in arms['psb'].values()),
           sum(r['status'].startswith('ok') for r in arms['ground'].values()),
           sum(r['status'].startswith('ok') for r in arms['synth'].values()))
          == (98, 87, 99, 99))

    # 3. independent per-case correctness recomputation
    by_id = {r['case_id']: r for r in rows}
    correct = {'h0': 0, 'psb': 0, 'grs': 0}
    h0_valid = grs_valid = 0
    h0_unsafe = grs_unsafe = 0
    c0_cd = c2_cd = 0
    h0_ok_ids, grs_ok_ids = set(), set()
    for case_id, row in by_id.items():
        worlds = row['worlds']
        adm = row['admissible_program_sets']
        # H0
        h0row = arms['h0'][case_id]
        h0c = False
        if h0row['prediction'] is not None:
            try:
                program = v3.compile_v3_structure(dict(h0row['prediction']))
                for probe in [frozenset()] + [frozenset([a]) for a in row['atom_catalog'][:8]]:
                    v3.evaluate_v3_program(program, probe)
                h0c, per_world = psb.score_program_set([program], worlds, adm)
                h0_valid += 1
                if any(w.get('verdict') == 'PERMITTED'
                       and 'PERMITTED' not in w.get('acceptable', [])
                       for w in per_world or []):
                    h0_unsafe += 1
            except (v3.StructureInvalid, ValueError, TypeError):
                pass
        correct['h0'] += h0c
        if h0c:
            h0_ok_ids.add(case_id)
            c0_cd += 1
        # PSB
        prow = arms['psb'][case_id]
        if prow['prediction'] is not None:
            try:
                programs, _ = psb.compile_psb_graph(dict(prow['prediction']),
                                                    permission_gate=False)
                correct['psb'] += psb.score_program_set(programs, worlds, adm)[0]
            except (psb.PSBInvalid, ValueError, TypeError):
                pass
        # GRS (synth + grounded inventory + canonicalizer)
        srow = arms['synth'][case_id]
        pred = srow['prediction']
        if isinstance(pred, dict) and pred.get('ground_inventory') \
                and isinstance(pred.get('dsl'), str):
            try:
                alternatives, _d, _a = em.compile_b3(pred['dsl'],
                                                     pred['ground_inventory'])
                grs_valid += 1
                ok, per_world = grs.grs_score_prediction(alternatives, worlds, adm)
                correct['grs'] += ok
                if len(alternatives) == 1 and ok:
                    c2_cd += 1
                    grs_ok_ids.add(case_id)
                for w in per_world or []:
                    verdicts = w.get('verdicts') or [w.get('verdict')]
                    if any(v == 'PERMITTED' for v in verdicts) \
                            and 'PERMITTED' not in w.get('acceptable', []):
                        grs_unsafe += 1
                        break
            except (em.EmissionInvalid, grs.GRSInvalid, ValueError, TypeError):
                pass

    check('C0 correct-definitive = 60', c0_cd == 60)
    check('C2 correct-definitive = 81', c2_cd == 81)
    check('PSB correct = 17', correct['psb'] == 17)
    check('H0 unsafe = 14', h0_unsafe == 14)
    check('C2 unsafe = 2', grs_unsafe == 2)
    check('C2 vs C0 corrections = 30', len(grs_ok_ids - h0_ok_ids) == 30)
    check('C2 vs C0 regressions = 9', len(h0_ok_ids - grs_ok_ids) == 9)
    check('H0/GRS oracle union = 90', len(h0_ok_ids | grs_ok_ids) == 90)
    check('results verdict KEEP_H0', results['verdict'] == 'KEEP_H0')
    check('results C2 cdc matches', results['candidates']['C2_GRS_refined']
          ['correct_definitive_coverage'] == 0.81)
    check('results C0 cdc matches', results['candidates']['C0_H0']
          ['correct_definitive_coverage'] == 0.60)
    check('audit PSB ACTOR class = 54',
          audit['arm_taxonomy']['psb'].get('ACTOR') == 54)
    check('audit GRS LEAF_GROUNDING = 4',
          audit['arm_taxonomy']['grs_synth'].get('LEAF_GROUNDING') == 4)

    failed = [name for name, ok in CHECKS if not ok]
    print(json.dumps({'checks_passed': sum(1 for _, ok in CHECKS if ok),
                      'checks_total': len(CHECKS), 'failed': failed}, indent=1))
    return 0 if not failed else 1


if __name__ == '__main__':
    raise SystemExit(main())
