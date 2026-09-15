"""Deterministic failure audit + closure report for the C-ALR reimplementation
study (policy_c_alr_reimpl_v1). Runs ONLY after the H0 seal and (here) the
Stage A' REJECT_EARLY verdict; reads sealed artifacts only; no LLM, no network,
no manual rescoring. Emits:
  outputs/vnext/policy_c_alr_reimpl_v1_failure_audit.json
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
sys.path.insert(0, str(REPO / 'scripts'))

from guardian_truth.vnext import policy_v3_benchmark as v3
from guardian_truth.vnext import policy_v5_benchmark as v5
from guardian_truth.vnext.integrity import digest, file_digest, prediction_seal

import evaluate_vnext_c_alr_reimpl as runner

PREFIX = runner.PREFIX
OUT = REPO / 'outputs/vnext'


def classify(program, gold):
    """Deterministic error-class taxonomy for a wrong phi vs gold (diagnostic)."""
    if program is None:
        return 'NO_VALID_STRUCTURE'
    diffs = []
    conds_p, conds_g = program['condition_literals'], gold['condition_literals']
    excs_p, excs_g = program['exception_literals'], gold['exception_literals']
    if sorted(conds_p) != sorted(conds_g):
        diffs.append('condition_literals')
    if sorted(excs_p) != sorted(excs_g):
        diffs.append('exception_literals')
    if program['modality'] != gold['modality']:
        diffs.append('modality')
    if program['relation'] != gold['relation']:
        diffs.append('relation')
    if program['target_clauses'] != gold['target_clauses']:
        diffs.append('target_clauses')
    if program['condition_mode'] != gold['condition_mode']:
        diffs.append('condition_mode')
    if program['exception_mode'] != gold['exception_mode']:
        diffs.append('exception_mode')
    if program['temporal'] != gold['temporal']:
        diffs.append('temporal')
    for field in ('regulated_kind', 'facet', 'identity', 'provenance',
                  'quantification', 'actor'):
        if program[field] != gold[field]:
            diffs.append(field)
    # relocation pattern: same literal set moved between condition and exception
    def _flip(lit):
        return lit[1:] if lit.startswith('!') else '!' + lit
    if sorted(conds_p) == sorted(excs_g) and sorted(excs_p) == sorted(conds_g) \
            and (conds_p or excs_p) and conds_p != conds_g:
        pattern = 'UNLESS_EXCEPTION_PLACED_AS_CONDITION'
    elif conds_p != conds_g and sorted(conds_p) == sorted(_flip(l) for l in conds_g):
        pattern = 'CONDITION_NEGATION_FLIP'
    elif diffs == ['modality']:
        pattern = 'MODALITY_ONLY'
    else:
        pattern = 'MULTI_AXIS'
    return pattern, diffs


def main():
    freeze, cases = runner.load_freeze(REPO, OUT)
    rows = json.loads((OUT / f'{PREFIX}_predictions.json').read_text(encoding='utf-8'))
    seal = json.loads((OUT / f'{PREFIX}_prediction_seal.json').read_text(encoding='utf-8'))
    expected = prediction_seal(rows, [case.case_id for case in cases],
                               architecture_commit=freeze['architecture_commit'],
                               configuration_sha256=digest(freeze))
    if seal != expected:
        raise ValueError('h0 seal invalid')
    stage_a = json.loads((OUT / f'{PREFIX}_stage_a.json').read_text(encoding='utf-8'))
    by_id = {row['case_id']: row for row in rows}
    audit = []
    for case in cases:
        row = by_id[case.case_id]
        phi = row['prediction']
        ok = bool(phi) and v3.score_candidate_structure(
            dict(phi), case.worlds, case.admissible_programs)[0]
        if ok:
            continue
        gold = v3.compile_v3_structure(dict(case.admissible_structures[0]))
        program = None
        pattern, fields = 'NO_VALID_STRUCTURE', []
        if phi is not None:
            try:
                program = v3.compile_v3_structure(dict(phi))
                pattern, fields = classify(program, gold)
            except v3.StructureInvalid:
                pass
        catalog_reachable = []
        if program is not None:
            for gold_structure in case.admissible_structures:
                gold_p = v3.compile_v3_structure(dict(gold_structure))
                mutations = runner.catalog_diff(program, gold_p)
                if mutations is not None:
                    catalog_reachable.append({'mutations': mutations,
                                              'count': len(mutations)})
        worlds = []
        if phi:
            _, per_world, _ = v3.score_candidate_structure(
                dict(phi), case.worlds, case.admissible_programs)
            worlds = [w for w in (per_world or []) if not w['match']]
        audit.append({'case_id': case.case_id, 'family': case.family,
                      'style': case.style, 'ambiguous': case.ambiguous,
                      'trap': case.trap, 'status': row['status'],
                      'error_pattern': pattern, 'differing_fields': fields,
                      'catalog_paths': catalog_reachable,
                      'mismatching_worlds': len(worlds),
                      'first_mismatch': worlds[:1]})
    summary = {'n_cases': len(cases), 'h0_correct': stage_a['summary']['h0_correct'],
               'h0_wrong': len(audit), 'h0_accuracy': stage_a['summary']['h0_accuracy'],
               'recoverable': stage_a['summary']['recoverable'],
               'verdict': stage_a['verdict'],
               'error_patterns': {}}
    for entry in audit:
        key = f"{entry['error_pattern']}|{'/'.join(entry['differing_fields'][:3])}"
        summary['error_patterns'][key] = summary['error_patterns'].get(key, 0) + 1
    report = {'experiment': PREFIX,
              'source_seal_sha256': file_digest(OUT / f'{PREFIX}_prediction_seal.json'),
              'source_stage_a_sha256': file_digest(OUT / f'{PREFIX}_stage_a.json'),
              'verifier_requests_sent': 0,
              'note': 'Stage A prime STOP gate fired (recoverable share 0.0 < 0.05, '
                      'oracle gain 0.0 < 0.04 pp); per the frozen study protocol no '
                      'verifier request was ever sent; H0 is the terminal result of '
                      'this study.',
              'summary': summary, 'cases': audit}
    out_path = OUT / f'{PREFIX}_failure_audit.json'
    if out_path.exists():
        existing = json.loads(out_path.read_text(encoding='utf-8'))
        if digest(existing) != digest(report):
            raise ValueError('failure audit changed on recompute')
    else:
        from guardian_truth.vnext.integrity import write_new
        write_new(out_path, report)
    print(json.dumps({'audit_cases': len(audit), 'patterns': summary['error_patterns'],
                      'verdict': summary['verdict']}, indent=1))


if __name__ == '__main__':
    main()
