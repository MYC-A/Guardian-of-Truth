"""Independent post-hoc revalidation of the sealed GRS Stage A results.

Re-derives every published number from the sealed artifacts alone
(freeze, benchmark, prediction seals, results, audit) without touching the
runner's scoring code paths where possible, and cross-checks the frozen
gates and the terminal verdict.  Deterministic; no network; no LLM.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from guardian_truth.vnext import policy_grs as grs  # noqa: E402
from guardian_truth.vnext import policy_psb as psb  # noqa: E402
from guardian_truth.vnext import policy_v3_benchmark as v3  # noqa: E402
from guardian_truth.vnext.integrity import digest, file_digest  # noqa: E402
from guardian_truth.vnext import policy_grs_causal_benchmark as corpus  # noqa: E402

OUT = ROOT / 'outputs/vnext'
PREFIX = 'policy_grs_stage_a_v1'
CHECKS: list[tuple[str, bool]] = []


def check(name: str, ok: bool) -> None:
    CHECKS.append((name, bool(ok)))


def main() -> int:
    freeze = json.loads((OUT / f'{PREFIX}_freeze.json').read_text(encoding='utf-8'))
    bench = json.loads((OUT / f'{PREFIX}_benchmark.json').read_text(encoding='utf-8'))
    results = json.loads((OUT / f'{PREFIX}_results.json').read_text(encoding='utf-8'))
    audit = json.loads((OUT / 'policy_grs_v1_failure_audit.json').read_text(encoding='utf-8'))

    # 1. storage integrity
    check('benchmark hash', freeze['benchmark_sha256']
          == file_digest(OUT / f'{PREFIX}_benchmark.json'))
    check('gold frozen before predictions', freeze['gold_frozen_before_predictions'] is True
          and freeze['gold_joined'] is False)
    check('prereg hash', freeze['prereg_sha256'] == file_digest(ROOT / freeze['prereg']))

    # 2. benchmark regeneration determinism (gold identity)
    cases = corpus.build_grs_stage_a_benchmark()
    check('case ids', freeze['case_ids'] == [case.case_id for case in cases])
    check('gold dsl hash', freeze['gold_dsl_sha256']
          == digest({case.case_id: case.gold_dsl for case in cases}))
    check('gold inventory hash', freeze['gold_inventory_sha256']
          == digest({case.case_id: case.oracle_inventory for case in cases}))
    by_id = {case.case_id: case for case in cases}

    # 3. seals
    for arm in ('a0', 'a1'):
        rows = json.loads((OUT / f'{PREFIX}_{arm}_predictions.json').read_text(encoding='utf-8'))
        seal = json.loads((OUT / f'{PREFIX}_{arm}_prediction_seal.json').read_text(encoding='utf-8'))
        check(f'{arm} seal prediction hash', seal['prediction_sha256'] == digest(rows))
        check(f'{arm} seal case ids', seal['case_ids_sha256']
              == digest(freeze['case_ids']))
        check(f'{arm} seal gold not joined', seal['gold_joined'] is False)
        check(f'{arm} row coverage', [r['case_id'] for r in rows] == freeze['case_ids'])

    # 4. independent rescoring of both arms
    rows = {arm: {r['case_id']: r for r in json.loads(
        (OUT / f'{PREFIX}_{arm}_predictions.json').read_text(encoding='utf-8'))}
        for arm in ('a0', 'a1')}
    correct = {'a0': 0, 'a1': 0}
    valid_a1 = 0
    resolved = 0
    unsafe = {'a0': 0, 'a1': 0}
    binding_pred: dict = {'a0': {}, 'a1': {}}
    binding_gold: dict = {}
    for case in cases:
        admissible = [tuple(dict(p) for p in s)
                      for s in bench['cases'][[c.case_id for c in cases].index(case.case_id)]
                      ['admissible_program_sets']]
        gold_triples = set()
        for program in case.admissible_program_sets[0]:
            gold_triples |= psb.canonical_triples_flat(program)
        binding_gold[case.case_id] = gold_triples
        # A0
        pred = rows['a0'][case.case_id]['prediction']
        if pred is not None:
            try:
                program = v3.compile_v3_structure(dict(pred))
                ok, per = psb.score_program_set([program], case.worlds,
                                                case.admissible_program_sets)
                correct['a0'] += ok
                binding_pred['a0'][case.case_id] = psb.canonical_triples_flat(program)
                for world in per or []:
                    if world['verdict'] == 'PERMITTED' \
                            and 'PERMITTED' not in world['acceptable']:
                        unsafe['a0'] += 1
                        break
            except (v3.StructureInvalid, ValueError, TypeError):
                pass
        # A1
        pred = rows['a1'][case.case_id]['prediction']
        if rows['a1'][case.case_id]['status'].startswith('ok'):
            valid_a1 += 1
        if pred is not None and isinstance(pred.get('dsl'), str):
            try:
                alternatives, dropped = grs.compile_dsl(pred['dsl'],
                                                        case.oracle_inventory)
                ok, per = grs.grs_score_prediction(alternatives, case.worlds,
                                                   case.admissible_program_sets)
                correct['a1'] += ok
                if not dropped:
                    resolved += 1
                triples = set()
                for program in alternatives[0]:
                    triples |= psb.canonical_triples_flat(program)
                binding_pred['a1'][case.case_id] = triples
                for world in per or []:
                    if any(v == 'PERMITTED' for v in world.get('verdicts', [])) \
                            and 'PERMITTED' not in world.get('acceptable', []):
                        unsafe['a1'] += 1
                        break
            except (grs.GRSInvalid, ValueError, TypeError):
                pass
    n = len(cases)
    check('A0 accuracy', results['primary_metric']['a0']['correct'] == correct['a0'])
    check('A1 accuracy', results['primary_metric']['a1']['correct'] == correct['a1'])
    check('A1 validity', round(valid_a1 / n, 4) == results['validity']['a1'])
    check('resolved coverage', round(resolved / n, 4) == results['resolved_coverage_a1'])
    check('unsafe a0', results['unsafe_permission_cases']['a0'] == unsafe['a0'])
    check('unsafe a1', results['unsafe_permission_cases']['a1'] == unsafe['a1'])

    # 5. binding F1 aggregate
    for arm, key in (('a0', 'a0_flat_projection'), ('a1', 'a1_compiled')):
        metrics = psb.binding_metrics(binding_pred[arm], binding_gold)
        check(f'binding f1 {arm}',
              abs((metrics['aggregate']['f1'] or 0)
                  - (results['binding_attachment'][key]['aggregate']['f1'] or 0)) < 1e-9)

    # 6. paired statistics
    pairs = results['paired_statistics']['a1_vs_a0']
    corrections = sum(1 for c in cases
                      if not _ok_a0(c, rows, by_id) and _ok_a1(c, rows, by_id))
    regressions = sum(1 for c in cases
                      if _ok_a0(c, rows, by_id) and not _ok_a1(c, rows, by_id))
    check('paired corrections', pairs['corrections'] == corrections)
    check('paired regressions', pairs['regressions'] == regressions)
    h0_correct = sum(1 for c in cases if _ok_a0(c, rows, by_id))
    check('regression gate count', results['regression_gate']['n_h0_correct'] == h0_correct)
    check('regression rate', results['regression_gate']['rate']
          == round(regressions / h0_correct, 4))

    # 7. gates and verdict
    ge = results['gates_evaluation']['evaluation']
    check('gate behavioral', ge['behavioral_pass'] == (correct['a1'] / n >= 0.85))
    check('gate validity', ge['validity_pass'] == (valid_a1 / n >= 0.95))
    capacity_cases = [c for c in cases if not c.h0_representable]
    cap = sum(_ok_a1(c, rows, by_id) for c in capacity_cases)
    check('gate capacity', ge['capacity_pass'] == (cap / len(capacity_cases) >= 0.75))
    nl_cases = [c for c in cases if c.cohort == 'nl_prose_stress']
    nl = sum(_ok_a1(c, rows, by_id) for c in nl_cases)
    check('gate nl', ge['nl_pass'] == (nl / len(nl_cases) >= 0.75))
    check('gate regression', ge['regression_pass'] == (regressions / h0_correct <= 0.10))
    check('verdict follows gates',
          results['verdict'] == ('PASS_STAGE_A' if ge['all_pass']
                                 else 'REJECT_GRS_COMPOSITION'))
    check('verdict is terminal reject', results['verdict'] == 'REJECT_GRS_COMPOSITION')

    # 8. audit consistency
    a1_errors = audit['stages']['A']['arms']['a1']
    check('audit error count matches 7-case deficit',
          a1_errors['error_count'] == n - correct['a1'])
    dsl_invalid = [e for e in a1_errors['errors'] if e['classification'] == 'DSL_INVALID']
    check('five DSL_INVALID serialization slips', len(dsl_invalid) == 5)
    check('all regressions are the DSL slips',
          {e['case_id'] for e in dsl_invalid}
          == {c.case_id for c in cases
              if _ok_a0(c, rows, by_id) and not _ok_a1(c, rows, by_id)})
    wrapper_slip = 0
    for e in dsl_invalid:
        dsl = (rows['a1'][e['case_id']]['prediction'] or {}).get('dsl', '')
        if dsl.startswith('RULESET(PERMIT,') or dsl.startswith('RULESET(REQUIRE,') \
                or dsl.startswith('RULESET(PROHIBIT,'):
            wrapper_slip += 1
    check('all five are the omitted RULE(...) wrapper', wrapper_slip == 5)

    # 9. zero hallucination invariant (per-case scan of that case's outputs)
    attempts = 0
    case_ids = freeze['case_ids']
    for index, case in enumerate(cases):
        for path in sorted(OUT.glob(
                f'{PREFIX}_a1_{index:03d}_request_*_result.json')):
            artifact = json.loads(path.read_text(encoding='utf-8'))
            payload = (artifact.get('proposal') or {}).get('payload_json')
            if payload:
                try:
                    value = json.loads(payload)
                except ValueError:
                    continue
                if isinstance(value, dict) and isinstance(value.get('dsl'), str):
                    attempts += sum(grs.hallucination_attempts(
                        value['dsl'], case.oracle_inventory)[k] for k in
                        ('unknown_reference_attempts',
                         'out_of_grammar_operator_attempts',
                         'free_text_leaf_attempts'))
    check('zero hallucination attempts across all persisted outputs', attempts == 0)

    failed = [name for name, ok in CHECKS if not ok]
    for name, ok in CHECKS:
        print(('PASS ' if ok else 'FAIL ') + name)
    print(f'\n{len(CHECKS) - len(failed)}/{len(CHECKS)} checks pass')
    return 1 if failed else 0


def _ok_a0(case, rows, by_id):
    pred = rows['a0'][case.case_id]['prediction']
    if pred is None:
        return False
    try:
        program = v3.compile_v3_structure(dict(pred))
    except (v3.StructureInvalid, ValueError, TypeError):
        return False
    ok, _ = psb.score_program_set([program], case.worlds,
                                  case.admissible_program_sets)
    return ok


def _ok_a1(case, rows, by_id):
    pred = rows['a1'][case.case_id]['prediction']
    if pred is None or not isinstance(pred.get('dsl'), str):
        return False
    try:
        alternatives, _dropped = grs.compile_dsl(pred['dsl'],
                                                 case.oracle_inventory)
    except (grs.GRSInvalid, ValueError, TypeError):
        return False
    ok, _ = grs.grs_score_prediction(alternatives, case.worlds,
                                     case.admissible_program_sets)
    return ok


if __name__ == '__main__':
    raise SystemExit(main())
