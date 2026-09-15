"""Final Policy cycle - Stage B: GRS emission-boundary refinement (DEV ONLY).

User sections 29-36: the OLD GRS Stage A corpus is used ONLY as a
development corpus.  Semantic targets are unchanged; the technical target
is to remove purely representational / serialization failures without
changing semantics.  Arms:

  B1        sealed Stage A direct-DSL arm (baseline, never re-run)
  B3-replay deterministic canonicalizer applied to the sealed B1 outputs
            (zero API calls) + semantic preservation audit
  B2        live: per-rule structured JSON proposal + trusted assembler
  B3        live: permissive DSL + deterministic canonicalizer
  ground    live: frozen GRS grounder (catalog-only atoms, exact spans)
  e2e       live: grounder -> selected synthesis boundary (deployable shape)

Dev selection rule (frozen in freeze-dev BEFORE any live call): the e2e arm
uses B2 if B2 meets the dev emission criteria (validity >= 95%, behavioral
correctness >= sealed B1, hallucination attempts zero, H0-correct
regression rate <= 10%); else B3 if it meets them; else the e2e arm is
skipped and refined GRS is not shortlisted as deployable.

Nothing here is used as a prospective generalization claim; the fresh final
holdout is a separate frozen benchmark.

Phases: canon-audit | freeze-dev | smoke | run-b2 | run-b3 | run-ground |
         run-e2e | score-dev | status
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))

from guardian_truth.llm_client import ChatClient, ClientConfig
from guardian_truth.runtime import provider_config
from guardian_truth.settings import load_env_file
from guardian_truth.vnext.experiment import PersistedSemanticBackend, ProviderPause
from guardian_truth.vnext.integrity import digest, file_digest, prediction_seal, write_new
from guardian_truth.vnext.latency import percentile
from guardian_truth.vnext.semantic_v2 import DiagnosticSemanticBackend

from guardian_truth.vnext import policy_v3_benchmark as v3
from guardian_truth.vnext import policy_psb as psb
from guardian_truth.vnext import policy_grs as grs
from guardian_truth.vnext import policy_grs_emission as em
from guardian_truth.vnext import policy_grs_causal_benchmark as grs_corpus

import evaluate_vnext_policy_grs as grs_runner  # frozen Stage B grounder machinery

OUT = ROOT / 'outputs' / 'vnext'
PREFIX = 'policy_final_v1_dev'
SEALED_PREFIX = 'policy_grs_stage_a_v1'
DEVFREEZE_PATH = OUT / 'policy_final_v1_devfreeze.json'
DEVREPORT_PATH = OUT / 'policy_final_v1_grs_dev.json'

MODEL, PROVIDER = 'qwen3.8-flash', 'bai'

SOURCES = [
    'src/guardian_truth/vnext/policy_grs.py',
    'src/guardian_truth/vnext/policy_grs_emission.py',
    'src/guardian_truth/vnext/policy_grs_causal_benchmark.py',
    'src/guardian_truth/vnext/policy_v3_benchmark.py',
    'src/guardian_truth/vnext/policy_psb.py',
    'scripts/evaluate_vnext_policy_grs.py',
    'scripts/policy_final_grs_dev.py',
]

DEV_EMISSION_CRITERIA = {
    'validity_gte': 0.95,
    'correctness_gte_sealed_b1': True,
    'hallucination_attempts_eq': 0,
    'h0_correct_regression_rate_lte': 0.10,
}

SUPERSEDED_RUNNER_SHA256 = None
CURRENT_RUNNER_SHA256 = None

SMOKE_POLICY = 'Late-shift porters may refill the hydration station, unless the duty log is sealed.'
SMOKE_CATALOG = ['action:refill_hydration_station', 'state:duty_log_sealed',
                 'actor:assistant', 'distractor:smoke_case']
SMOKE_INVENTORY = {
    'facts': [
        {'id': 'F1', 'kind': 'ACTION', 'atom': 'action:refill_hydration_station',
         'span': 'refill the hydration station'},
        {'id': 'F2', 'kind': 'STATE', 'atom': 'state:duty_log_sealed',
         'span': 'the duty log is sealed'},
        {'id': 'F3', 'kind': 'ACTOR', 'atom': 'actor:assistant',
         'span': 'Late-shift porters'}],
    'markers': [
        {'id': 'M1', 'kind': 'MODAL_MARKER', 'value': 'PERMIT', 'span': 'may'},
        {'id': 'R1', 'kind': 'RELATION_MARKER', 'value': 'UNLESS',
         'span': 'unless'}],
}


# ------------------------------------------------------------------- helpers

def _commit_clean(root: Path) -> str:
    status = subprocess.run(['git', 'status', '--porcelain'], cwd=root,
                            capture_output=True, text=True, check=True).stdout
    if status.strip():
        raise ValueError(f'working tree not clean:\n{status}')
    return subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root,
                          capture_output=True, text=True, check=True).stdout.strip()


def _load_dev_corpus():
    """GRS Stage A corpus, identity-verified against the sealed freeze."""
    freeze = json.loads((OUT / f'{SEALED_PREFIX}_freeze.json').read_text(encoding='utf-8'))
    cases = grs_corpus.build_grs_stage_a_benchmark()
    if freeze['case_ids'] != [case.case_id for case in cases]:
        raise ValueError('sealed GRS case identity mismatch')
    if freeze['gold_dsl_sha256'] != digest({c.case_id: c.gold_dsl for c in cases}):
        raise ValueError('sealed GRS gold dsl mismatch')
    if freeze['gold_inventory_sha256'] != digest(
            {c.case_id: c.oracle_inventory for c in cases}):
        raise ValueError('sealed GRS gold inventory mismatch')
    if freeze['benchmark_sha256'] != file_digest(OUT / f'{SEALED_PREFIX}_benchmark.json'):
        raise ValueError('sealed GRS benchmark storage hash mismatch')
    return freeze, cases


def _load_sealed_arm(arm):
    freeze = json.loads((OUT / f'{SEALED_PREFIX}_freeze.json').read_text(encoding='utf-8'))
    rows = json.loads((OUT / f'{SEALED_PREFIX}_{arm}_predictions.json').read_text(encoding='utf-8'))
    seal = json.loads((OUT / f'{SEALED_PREFIX}_{arm}_prediction_seal.json').read_text(encoding='utf-8'))
    expected = prediction_seal(rows, freeze['case_ids'],
                               architecture_commit=freeze['architecture_commit'],
                               configuration_sha256=digest(freeze))
    if seal != expected:
        raise ValueError(f'sealed {arm} arm seal invalid')
    return {row['case_id']: row for row in rows}


def _load_devfreeze():
    freeze = json.loads(DEVFREEZE_PATH.read_text(encoding='utf-8'))
    source_checks = dict(freeze['source_sha256'])
    # disclosed supersession: this runner's own hash may drift for post-seal
    # scoring fixes (predictions/seals/freeze untouched); every other frozen
    # source must still match byte-exactly. The freeze dict itself is NEVER
    # mutated here - seals hash it.
    global SUPERSEDED_RUNNER_SHA256, CURRENT_RUNNER_SHA256
    SUPERSEDED_RUNNER_SHA256 = source_checks.pop('scripts/policy_final_grs_dev.py', None)
    CURRENT_RUNNER_SHA256 = file_digest(ROOT / 'scripts/policy_final_grs_dev.py')
    for name, expected in source_checks.items():
        if file_digest(ROOT / name) != expected:
            raise ValueError(f'dev freeze source mismatch: {name}')
    _, cases = _load_dev_corpus()
    if freeze['case_ids'] != [case.case_id for case in cases]:
        raise ValueError('dev freeze case identity mismatch')
    return freeze, cases


def _make_delegate():
    config = provider_config(ClientConfig(timeout_seconds=180, max_output_tokens=2048,
                                          max_retries=0, response_format_mode='none'),
                             PROVIDER, model=MODEL)
    live: list = []
    delegate = DiagnosticSemanticBackend(ChatClient(config), interval_seconds=10,
                                         checkpoint=live.append)
    return delegate, live


def _arm_metrics(rows_by_case, cases, compile_meaning, hallucinate, is_sealed_b1=False):
    """Dev metrics for one synthesis arm over the dev corpus."""
    per_case = {}
    for case in cases:
        row = rows_by_case[case.case_id]
        meaning, valid = compile_meaning(row, case)
        if meaning is None:
            correct, per_world = False, None
        else:
            correct, per_world = grs.grs_score_prediction(
                meaning, case.worlds, case.admissible_program_sets)
        unsafe = False
        for world in per_world or []:
            verdicts = world.get('verdicts') or [world.get('verdict')]
            if any(v == 'PERMITTED' for v in verdicts) \
                    and 'PERMITTED' not in world.get('acceptable', []):
                unsafe = True
                break
        gold_triples = set()
        for program in case.admissible_program_sets[0]:
            gold_triples |= psb.canonical_triples_flat(program)
        pred_triples = set()
        if meaning:
            for program in meaning[0]:
                pred_triples |= psb.canonical_triples_flat(program)
        per_case[case.case_id] = {
            'valid': valid, 'correct': correct, 'unsafe_permission': unsafe,
            'status': row.get('status'),
            'pred_triples': pred_triples, 'gold_triples': gold_triples,
        }
    n = len(cases)
    valid_n = sum(1 for c in cases if per_case[c.case_id]['valid'])
    correct_n = sum(1 for c in cases if per_case[c.case_id]['correct'])
    unsafe_n = sum(1 for c in cases if per_case[c.case_id]['unsafe_permission'])
    # binding micro-F1 (pooled)
    pred_k = gold_k = match_k = 0
    for c in cases:
        pc = per_case[c.case_id]
        pred_k += len(pc['pred_triples'])
        gold_k += len(pc['gold_triples'])
        match_k += len(pc['pred_triples'] & pc['gold_triples'])
    precision = match_k / pred_k if pred_k else None
    recall = match_k / gold_k if gold_k else None
    f1 = (2 * precision * recall / (precision + recall)) \
        if precision and recall else None
    halluc = hallucinate(rows_by_case, cases)
    def subset(fn):
        members = [c for c in cases if fn(c)]
        k = sum(1 for c in members if per_case[c.case_id]['correct'])
        return {'n': len(members), 'correct': k,
                'accuracy': round(k / len(members), 4) if members else None}
    return {
        'n': n,
        'validity': round(valid_n / n, 4),
        'correct': correct_n,
        'accuracy': round(correct_n / n, 4),
        'unsafe_permission_cases': unsafe_n,
        'binding_micro_f1': round(f1, 4) if f1 else None,
        'hallucination_attempts': halluc,
        'subsets': {
            'simple_controls': subset(lambda c: c.cohort == 'simple_controls'),
            'capacity_non_h0_representable': subset(lambda c: not c.h0_representable),
            'nl_prose_stress': subset(lambda c: c.cohort == 'nl_prose_stress'),
        },
        'per_case': {cid: {k: v for k, v in pc.items()
                           if k not in ('pred_triples', 'gold_triples')}
                     for cid, pc in per_case.items()},
    }


def _h0_correct(cases):
    rows = _load_sealed_arm('a0')
    out = {}
    for case in cases:
        row = rows[case.case_id]
        prediction = row['prediction']
        if prediction is None:
            out[case.case_id] = False
            continue
        try:
            program = v3.compile_v3_structure(dict(prediction))
            out[case.case_id] = psb.score_program_set(
                [program], case.worlds, case.admissible_program_sets)[0]
        except (v3.StructureInvalid, ValueError, TypeError):
            out[case.case_id] = False
    return out


def _regression_stats(per_case, h0_correct_map):
    h0_correct_n = sum(1 for v in h0_correct_map.values() if v)
    regressions = [cid for cid, ok in h0_correct_map.items()
                   if ok and not per_case[cid]['correct']]
    corrections = [cid for cid, ok in h0_correct_map.items()
                   if not ok and per_case[cid]['correct']]
    return {'h0_correct_baseline': h0_correct_n,
            'regressions': len(regressions), 'regression_ids': regressions,
            'regression_rate': round(len(regressions) / h0_correct_n, 4)
            if h0_correct_n else None,
            'corrections': len(corrections), 'correction_ids': corrections}


# --------------------------------------------------------- canon-audit (B3-replay)

def phase_canon_audit() -> int:
    _, cases = _load_dev_corpus()
    b1_rows = _load_sealed_arm('a1')
    h0_map = _h0_correct(cases)

    identity_ok = identity_checked = 0
    recovered, unrecovered = [], []
    replay_rows = {}
    audits = {}
    for case in cases:
        row = b1_rows[case.case_id]
        prediction = row['prediction']
        dsl = prediction.get('dsl') if isinstance(prediction, dict) else None
        if row['status'].startswith('ok') and isinstance(dsl, str):
            # semantic preservation on already-valid outputs: identity
            canonical_text, audit = em.canonicalize_dsl(dsl)
            identity_checked += 1
            if not audit['changed'] and grs.parse_dsl(canonical_text) == grs.parse_dsl(dsl):
                identity_ok += 1
            replay_rows[case.case_id] = {'prediction': prediction,
                                         'status': row['status']}
            audits[case.case_id] = audit
        else:
            # B1 failure: attempt pure-format canonicalization
            try:
                canonical_text, audit = em.canonicalize_dsl(dsl if isinstance(dsl, str) else '')
                ast = grs.parse_dsl(canonical_text)
                grs.validate_ruleset_ast(ast, case.oracle_inventory)
                alternatives, dropped = grs.compile_ruleset_ast(ast, case.oracle_inventory)
                replay_rows[case.case_id] = {
                    'prediction': {'dsl': canonical_text},
                    'status': 'ok_canonicalized'}
                audits[case.case_id] = audit
                recovered.append({'case_id': case.case_id, 'audit': audit,
                                  'sealed_status': row['status'],
                                  'canonical_dsl': canonical_text})
            except (em.EmissionInvalid, grs.GRSInvalid, ValueError, TypeError):
                replay_rows[case.case_id] = {'prediction': None,
                                             'status': 'canon_failed'}
                unrecovered.append({'case_id': case.case_id,
                                    'sealed_status': row['status']})

    def compile_meaning(row, case):
        prediction = row['prediction']
        if prediction is None or not isinstance(prediction.get('dsl'), str):
            return None, False
        try:
            alternatives, _ = grs.compile_dsl(prediction['dsl'], case.oracle_inventory)
            return alternatives, True
        except (grs.GRSInvalid, ValueError, TypeError):
            return None, False

    def hallucinate(rows_by_case, cases):
        total = {'unknown_reference_attempts': 0,
                 'out_of_grammar_operator_attempts': 0,
                 'free_text_leaf_attempts': 0}
        for case in cases:
            row = rows_by_case[case.case_id]
            dsl = (row['prediction'] or {}).get('dsl')
            if isinstance(dsl, str):
                counts = grs.hallucination_attempts(dsl, case.oracle_inventory)
                for key in total:
                    total[key] += counts[key]
        return total

    metrics = _arm_metrics(replay_rows, cases, compile_meaning, hallucinate)
    regression = _regression_stats(metrics['per_case'], h0_map)

    report = {
        'schema_version': 'guardian-vnext-policy-final-dev-canon-audit-v1',
        'arm': 'B3-replay (deterministic canonicalizer on sealed B1 outputs)',
        'new_llm_calls': 0,
        'semantic_preservation_audit': {
            'identity_checked_on_valid_outputs': identity_checked,
            'identity_holds': identity_ok,
            'identity_violations': identity_checked - identity_ok,
            'b1_failures_recovered_by_pure_format_canonicalization': recovered,
            'b1_failures_not_recovered': unrecovered,
            'claim': 'canonicalization changed only surface wrappers '
                     '(token-delta = RULE/( ) triples per wrapper, nothing '
                     'removed); meaning of every already-valid output is '
                     'byte-identical; format correction is not semantic '
                     'correction',
        },
        'metrics': metrics,
        'regression_vs_h0': regression,
    }
    write_new(OUT / 'policy_final_v1_dev_canon_audit.json', report)
    print(json.dumps({
        'status': 'CANON_AUDIT_DONE',
        'identity_holds': f"{identity_ok}/{identity_checked}",
        'recovered': [r['case_id'] for r in recovered],
        'unrecovered': [u['case_id'] for u in unrecovered],
        'validity': metrics['validity'], 'accuracy': metrics['accuracy'],
        'hallucination': metrics['hallucination_attempts'],
        'regressions_vs_h0': regression['regressions'],
    }, indent=1))
    return 0


# ------------------------------------------------------------------ freeze/smoke

def phase_freeze_dev() -> int:
    if DEVFREEZE_PATH.exists():
        print(json.dumps({'status': 'DEVFREEZE_ALREADY_DONE'}))
        return 0
    commit = _commit_clean(ROOT)
    _, cases = _load_dev_corpus()
    sealed = json.loads((OUT / f'{SEALED_PREFIX}_freeze.json').read_text(encoding='utf-8'))
    freeze = {
        'schema_version': 'guardian-vnext-policy-final-devfreeze-v1',
        'purpose': 'development-phase freeze of the GRS emission boundaries '
                   'B2/B3 and the grounder e2e arm (final Policy cycle, user '
                   'sections 29-36); NOT a prospective holdout',
        'architecture_commit': commit,
        'sealed_grs_continuity': {
            'grs_module_sha256': file_digest(ROOT / 'src/guardian_truth/vnext/policy_grs.py'),
            'sealed_architecture_commit': sealed['architecture_commit'],
            'case_ids_sha256': digest(sealed['case_ids']),
        },
        'case_ids': [case.case_id for case in cases],
        'corpus': 'GRS Stage A (development only; identity verified vs the '
                  'sealed GRS freeze)',
        'arms': {
            'b2': {'task_sha256': digest(em.B2_SYNTH_TASK),
                   'repair_task_sha256': digest(em.B2_SYNTH_REPAIR_TASK),
                   'schema_sha256': digest(em.B2_SCHEMA),
                   'assembler': 'policy_grs_emission.assemble_b2 + frozen '
                                'validate_ruleset_ast + frozen compile'},
            'b3': {'task_sha256': digest(em.B3_SYNTH_TASK),
                   'repair_task_sha256': digest(em.B3_SYNTH_REPAIR_TASK),
                   'schema_sha256': digest(em.B3_DSL_SCHEMA),
                   'canonicalizer': 'policy_grs_emission.canonicalize_dsl '
                                    '(RULE-wrapper omission only) + frozen '
                                    'parser/validator/compiler'},
            'ground': {'task_sha256': digest(grs.GRS_GROUND_TASK),
                       'repair_task_sha256': digest(grs.GRS_GROUND_REPAIR_TASK),
                       'schema_sha256': digest(grs.GRS_GROUND_SCHEMA),
                       'postvalidation': 'evaluate_vnext_policy_grs.'
                                         '_postvalidate_ground (frozen)'},
            'e2e': {'selection_rule': 'B2 if B2 meets dev emission criteria '
                                      'else B3 if B3 meets them else SKIPPED',
                    'criteria': DEV_EMISSION_CRITERIA},
        },
        'dev_emission_criteria': DEV_EMISSION_CRITERIA,
        'model': MODEL, 'provider': PROVIDER,
        'retry_policy': 'one machine-validation-triggered repair re-ask per '
                        'call; client max_retries=0; abandoned request '
                        'captures never resent',
        'source_sha256': {name: file_digest(ROOT / name) for name in SOURCES},
    }
    write_new(DEVFREEZE_PATH, freeze)
    print(json.dumps({'status': 'DEV_FROZEN', 'architecture_commit': commit,
                      'cases': len(cases)}))
    return 0


def _smoke_common(delegate, out: Path, freeze: dict, live: list):
    stem = f'{PREFIX}_smoke'
    backend = PersistedSemanticBackend(delegate, out, stem,
                                       configuration_sha256=digest(freeze),
                                       live_records=live)
    b2 = backend.propose(em.B2_SYNTH_TASK,
                         {'policy_text': SMOKE_POLICY,
                          'inventory': SMOKE_INVENTORY}, em.B2_SCHEMA)
    b3 = backend.propose(em.B3_SYNTH_TASK,
                         {'policy_text': SMOKE_POLICY,
                          'inventory': SMOKE_INVENTORY}, em.B3_DSL_SCHEMA)
    ground = backend.propose(grs.GRS_GROUND_TASK,
                             {'policy_text': SMOKE_POLICY,
                              'atom_catalog': SMOKE_CATALOG}, grs.GRS_GROUND_SCHEMA)
    return b2, b3, ground, backend


def phase_smoke(env_file) -> int:
    freeze, _ = _load_devfreeze()
    smoke_path = OUT / f'{PREFIX}_smoke.json'
    if smoke_path.exists():
        print(json.dumps({'status': 'SMOKE_ALREADY_DONE'}))
        return 0
    load_env_file(env_file)
    delegate, live = _make_delegate()
    b2, b3, ground, backend = _smoke_common(delegate, OUT, freeze, live)
    smoke = {'schema_version': 'guardian-vnext-policy-final-dev-smoke-v1',
             'purpose': 'synthetic non-benchmark schema/provider smoke BEFORE '
                        'the first dev semantic request',
             'payloads_are_benchmark_cases': False, 'scored': False,
             'b2': {'transport': b2.transport_status, 'schema': b2.schema_status},
             'b3': {'transport': b3.transport_status, 'schema': b3.schema_status},
             'ground': {'transport': ground.transport_status,
                        'schema': ground.schema_status},
             'telemetry': [dict(r) for r in backend.records]}
    write_new(smoke_path, smoke)
    ok = all(p.transport_status == 'SUCCESS' for p in (b2, b3, ground))
    print(json.dumps({'status': 'SMOKE_OK' if ok else 'SMOKE_TRANSPORT_FAILED',
                      'b2_schema': b2.schema_status, 'b3_schema': b3.schema_status,
                      'ground_schema': ground.schema_status}))
    return 0 if ok else 2


# ------------------------------------------------------------------- live arms

def _run_synth_arm(env_file, minutes: float, arm: str) -> int:
    """B2 or B3: one synthesis call (+1 repair) per case, oracle inventory."""
    freeze, cases = _load_devfreeze()
    if not (OUT / f'{PREFIX}_smoke.json').exists():
        print(json.dumps({'status': 'NO_SMOKE'}))
        return 2
    rows_path = OUT / f'{PREFIX}_{arm}_predictions.json'
    if rows_path.exists():
        print(json.dumps({'status': 'ALREADY_SEALED', 'arm': arm}))
        return 0
    if arm == 'b2':
        task, schema, repair_task = em.B2_SYNTH_TASK, em.B2_SCHEMA, em.B2_SYNTH_REPAIR_TASK

        def compile_value(value, _case):
            if not isinstance(value, dict) or 'rules' not in value:
                raise em.EmissionInvalid('B2_INVALID: proposal must have rules')
            em.compile_b2(value, _case.oracle_inventory)
    else:
        task, schema, repair_task = em.B3_SYNTH_TASK, em.B3_DSL_SCHEMA, em.B3_SYNTH_REPAIR_TASK

        def compile_value(value, _case):
            if not isinstance(value, dict) or not isinstance(value.get('dsl'), str):
                raise em.EmissionInvalid('B3_INVALID: dsl field must be a string')
            em.compile_b3(value['dsl'], _case.oracle_inventory)
    load_env_file(env_file)
    delegate, live = _make_delegate()
    started = time.monotonic()
    rows = []
    for index, case in enumerate(cases):
        row_path = OUT / f'{PREFIX}_{arm}_case_{index:03d}.json'
        if row_path.exists():
            row = json.loads(row_path.read_text(encoding='utf-8'))
            if row['case_id'] != case.case_id \
                    or row['configuration_sha256'] != digest(freeze):
                raise ValueError(f'cached {arm} case changed')
        else:
            row = _run_one_case(delegate, OUT, freeze, index, case, live, arm,
                                task, schema, repair_task,
                                {'policy_text': case.policy,
                                 'inventory': case.oracle_inventory},
                                compile_value)
            write_new(row_path, row)
        rows.append(row)
        print(json.dumps({'arm': arm, 'completed': len(rows),
                          'total': len(cases), 'case_id': case.case_id,
                          'status': row['status']}), flush=True)
        if time.monotonic() - started > minutes * 60:
            print(json.dumps({'status': 'PARTIAL_TIME_BUDGET', 'arm': arm,
                              'completed': len(rows), 'total': len(cases)}),
                  flush=True)
            return 3
    prediction_rows = [{'case_id': r['case_id'], 'prediction': r['prediction'],
                        'status': r['status']} for r in rows]
    write_new(rows_path, prediction_rows)
    seal = prediction_seal(prediction_rows, [c.case_id for c in cases],
                           architecture_commit=freeze['architecture_commit'],
                           configuration_sha256=digest(freeze))
    write_new(OUT / f'{PREFIX}_{arm}_prediction_seal.json', seal)
    print(json.dumps({'status': 'SEALED', 'arm': arm, 'cases': len(rows),
                      'ok': sum(r['status'].startswith('ok') for r in rows)}),
          flush=True)
    return 0


def _run_one_case(delegate, out: Path, freeze: dict, index: int, case, live: list,
                  arm: str, task: str, schema: dict, repair_task: str,
                  payload: dict, compile_value):
    stem = f'{PREFIX}_{arm}_{index:03d}'
    backend = PersistedSemanticBackend(delegate, out, stem,
                                       configuration_sha256=digest(freeze),
                                       live_records=live)
    proposal = backend.propose(task, payload, schema)
    records = list(backend.records)
    value, status, error = None, None, None
    if proposal.transport_status != 'SUCCESS' or proposal.schema_status != 'VALID':
        status, error = 'parse_failed', (proposal.error_category or proposal.schema_status)
    else:
        value = proposal.value
        try:
            compile_value(value, case)
            status = 'ok'
        except (ValueError, TypeError) as failure:
            status, error = 'compile_failed', str(failure)
    if status != 'ok':
        repair_payload = dict(payload)
        repair_payload['previous_output'] = (proposal.payload_json
                                             if proposal.payload_json is not None else None)
        repair_payload['machine_error'] = error
        repair = backend.propose(repair_task, repair_payload, schema)
        records = list(backend.records)
        if repair.transport_status == 'SUCCESS' and repair.schema_status == 'VALID':
            try:
                value = repair.value
                compile_value(value, case)
                status, error = 'ok_repaired', None
            except (ValueError, TypeError) as failure:
                status, error = 'compile_failed_after_repair', str(failure)
        elif status == 'parse_failed':
            status = 'parse_failed_after_repair'
            error = repair.error_category or repair.schema_status
    return {'case_id': case.case_id, 'configuration_sha256': digest(freeze),
            'status': status, 'error': error, 'prediction': value,
            'request_records': records}


def phase_run_ground(env_file, minutes: float) -> int:
    freeze, cases = _load_devfreeze()
    if not (OUT / f'{PREFIX}_smoke.json').exists():
        print(json.dumps({'status': 'NO_SMOKE'}))
        return 2
    rows_path = OUT / f'{PREFIX}_ground_predictions.json'
    if rows_path.exists():
        print(json.dumps({'status': 'ALREADY_SEALED', 'arm': 'ground'}))
        return 0
    load_env_file(env_file)
    delegate, live = _make_delegate()
    started = time.monotonic()
    rows = []
    for index, case in enumerate(cases):
        row_path = OUT / f'{PREFIX}_ground_case_{index:03d}.json'
        if row_path.exists():
            row = json.loads(row_path.read_text(encoding='utf-8'))
            if row['case_id'] != case.case_id \
                    or row['configuration_sha256'] != digest(freeze):
                raise ValueError('cached ground case changed')
        else:
            def compile_value(value, _case=case):
                grs_runner._postvalidate_ground(value, _case.policy,
                                                _case.atom_catalog)
            row = _run_one_case(delegate, OUT, freeze, index, case, live,
                                'ground', grs.GRS_GROUND_TASK,
                                grs.GRS_GROUND_SCHEMA, grs.GRS_GROUND_REPAIR_TASK,
                                {'policy_text': case.policy,
                                 'atom_catalog': list(case.atom_catalog)},
                                compile_value)
            write_new(row_path, row)
        rows.append(row)
        print(json.dumps({'arm': 'ground', 'completed': len(rows),
                          'total': len(cases), 'case_id': case.case_id,
                          'status': row['status']}), flush=True)
        if time.monotonic() - started > minutes * 60:
            print(json.dumps({'status': 'PARTIAL_TIME_BUDGET', 'arm': 'ground',
                              'completed': len(rows), 'total': len(cases)}),
                  flush=True)
            return 3
    prediction_rows = [{'case_id': r['case_id'], 'prediction': r['prediction'],
                        'status': r['status']} for r in rows]
    write_new(rows_path, prediction_rows)
    seal = prediction_seal(prediction_rows, [c.case_id for c in cases],
                           architecture_commit=freeze['architecture_commit'],
                           configuration_sha256=digest(freeze))
    write_new(OUT / f'{PREFIX}_ground_prediction_seal.json', seal)
    print(json.dumps({'status': 'SEALED', 'arm': 'ground', 'cases': len(rows),
                      'ok': sum(r['status'].startswith('ok') for r in rows)}),
          flush=True)
    return 0


def _selected_boundary():
    """Frozen dev selection rule: B2 if it meets the dev emission criteria,
    else B3 if it meets them, else None."""
    freeze, cases = _load_devfreeze()
    b1_rows = _load_sealed_arm('a1')
    b1_correct = 0
    for case in cases:
        row = b1_rows[case.case_id]
        try:
            alts, _ = grs.compile_dsl(row['prediction']['dsl'], case.oracle_inventory) \
                if row['prediction'] else (None, None)
            if alts is not None:
                b1_correct += grs.grs_score_prediction(
                    alts, case.worlds, case.admissible_program_sets)[0]
        except (grs.GRSInvalid, ValueError, TypeError, KeyError, TypeError):
            pass
    h0_map = _h0_correct(cases)
    h0_n = sum(1 for v in h0_map.values() if v)
    for arm in ('b2', 'b3'):
        rows_path = OUT / f'{PREFIX}_{arm}_predictions.json'
        if not rows_path.exists():
            continue
        rows = {r['case_id']: r for r in json.loads(rows_path.read_text(encoding='utf-8'))}
        valid_n = correct_n = halluc = 0
        regressions = 0
        for case in cases:
            row = rows[case.case_id]
            meaning = _compile_dev_arm(arm, row, case)
            if meaning is None:
                continue
            valid_n += 1
            correct_n += grs.grs_score_prediction(
                meaning, case.worlds, case.admissible_program_sets)[0]
            if h0_map[case.case_id]:
                regressions += 0 if grs.grs_score_prediction(
                    meaning, case.worlds, case.admissible_program_sets)[0] else 1
            raw = row['prediction']
            if arm == 'b2':
                counts = em.b2_hallucination_attempts(raw, case.oracle_inventory)
            else:
                counts = grs.hallucination_attempts(raw.get('dsl', ''),
                                                    case.oracle_inventory)
            halluc += counts['unknown_reference_attempts'] \
                + counts['out_of_grammar_operator_attempts'] \
                + counts['free_text_leaf_attempts']
        n = len(cases)
        criteria = freeze['dev_emission_criteria']
        ok = (valid_n / n >= criteria['validity_gte']
              and correct_n >= b1_correct
              and halluc == criteria['hallucination_attempts_eq']
              and (regressions / h0_n if h0_n else 0) <= criteria['h0_correct_regression_rate_lte'])
        if ok:
            return arm, {'validity': round(valid_n / n, 4),
                         'correct': correct_n, 'hallucination': halluc,
                         'regressions': regressions, 'b1_correct': b1_correct}
    return None, {'b1_correct': b1_correct}


def _compile_dev_arm(arm, row, case):
    """Compile a sealed dev-arm row into GRS alternatives (None if invalid)."""
    prediction = row['prediction']
    if prediction is None:
        return None
    try:
        if arm == 'b2':
            alternatives, _, _ = em.compile_b2(prediction, case.oracle_inventory)
        elif arm == 'b3':
            alternatives, _, _ = em.compile_b3(prediction['dsl'],
                                               case.oracle_inventory)
        elif arm in ('e2e', 'e2ecanon'):
            ground_inventory = prediction.get('ground_inventory')
            synth = prediction.get('synth')
            if not ground_inventory or synth is None:
                return None
            if row.get('boundary') == 'b3':
                alternatives, _, _ = em.compile_b3(synth['dsl'], ground_inventory)
            elif row.get('boundary') == 'b1canon':
                alternatives, _, _ = em.compile_b3(synth['dsl'], ground_inventory)
            else:
                alternatives, _, _ = em.compile_b2(synth, ground_inventory)
        else:
            raise ValueError(f'unknown arm {arm}')
        return alternatives
    except (em.EmissionInvalid, grs.GRSInvalid, ValueError, TypeError, KeyError):
        return None


def phase_run_e2e(env_file, minutes: float) -> int:
    """grounder -> selected synthesis boundary, end-to-end dev arm."""
    freeze, cases = _load_devfreeze()
    if not (OUT / f'{PREFIX}_smoke.json').exists():
        print(json.dumps({'status': 'NO_SMOKE'}))
        return 2
    boundary, info = _selected_boundary()
    if boundary is None:
        print(json.dumps({'status': 'E2E_SKIPPED', 'reason':
                          'no boundary meets the frozen dev emission criteria',
                          'info': info}))
        return 0
    rows_path = OUT / f'{PREFIX}_e2e_predictions.json'
    if rows_path.exists():
        print(json.dumps({'status': 'ALREADY_SEALED', 'arm': 'e2e'}))
        return 0
    load_env_file(env_file)
    delegate, live = _make_delegate()
    task, schema, repair_task = (
        (em.B2_SYNTH_TASK, em.B2_SCHEMA, em.B2_SYNTH_REPAIR_TASK)
        if boundary == 'b2' else
        (em.B3_SYNTH_TASK, em.B3_DSL_SCHEMA, em.B3_SYNTH_REPAIR_TASK))
    started = time.monotonic()
    rows = []
    for index, case in enumerate(cases):
        row_path = OUT / f'{PREFIX}_e2e_case_{index:03d}.json'
        if row_path.exists():
            row = json.loads(row_path.read_text(encoding='utf-8'))
            if row['case_id'] != case.case_id \
                    or row['configuration_sha256'] != digest(freeze):
                raise ValueError('cached e2e case changed')
            rows.append(row)
            continue
        stem = f'{PREFIX}_e2e_{index:03d}'
        backend = PersistedSemanticBackend(delegate, OUT, stem,
                                           configuration_sha256=digest(freeze),
                                           live_records=live)
        # 1) grounder (+1 repair)
        ground_payload = {'policy_text': case.policy,
                          'atom_catalog': list(case.atom_catalog)}
        ground_proposal = backend.propose(grs.GRS_GROUND_TASK, ground_payload,
                                          grs.GRS_GROUND_SCHEMA)
        ground_status, ground_error, inventory = None, None, None
        if ground_proposal.transport_status != 'SUCCESS' \
                or ground_proposal.schema_status != 'VALID':
            ground_status = 'parse_failed'
            ground_error = ground_proposal.error_category or ground_proposal.schema_status
        else:
            try:
                inventory = grs_runner._postvalidate_ground(
                    ground_proposal.value, case.policy, case.atom_catalog)
                ground_status = 'ok'
            except (grs.GRSInvalid, ValueError, TypeError) as failure:
                ground_status, ground_error = 'compile_failed', str(failure)
        if ground_status != 'ok':
            repair_payload = dict(ground_payload)
            repair_payload['previous_output'] = (
                ground_proposal.payload_json
                if ground_proposal.payload_json is not None else None)
            repair_payload['machine_error'] = ground_error
            repair = backend.propose(grs.GRS_GROUND_REPAIR_TASK, repair_payload,
                                     grs.GRS_GROUND_SCHEMA)
            if repair.transport_status == 'SUCCESS' and repair.schema_status == 'VALID':
                try:
                    inventory = grs_runner._postvalidate_ground(
                        repair.value, case.policy, case.atom_catalog)
                    ground_status = 'ok_repaired'
                except (grs.GRSInvalid, ValueError, TypeError) as failure:
                    ground_status = 'ground_failed_after_repair'
                    ground_error = str(failure)
            else:
                ground_status = 'ground_failed_after_repair'
                ground_error = repair.error_category or repair.schema_status
        # 2) synthesizer over the GROUNDED inventory (+1 repair)
        synth_status, synth_error, synth_value = None, None, None
        if ground_status.startswith('ok'):
            synth_payload = {'policy_text': case.policy, 'inventory': inventory}
            synth_proposal = backend.propose(task, synth_payload, schema)
            if synth_proposal.transport_status != 'SUCCESS' \
                    or synth_proposal.schema_status != 'VALID':
                synth_status = 'parse_failed'
                synth_error = synth_proposal.error_category or synth_proposal.schema_status
            else:
                synth_value = synth_proposal.value
                try:
                    if boundary == 'b2':
                        em.compile_b2(synth_value, inventory)
                    else:
                        em.compile_b3(synth_value['dsl'], inventory)
                    synth_status = 'ok'
                except (ValueError, TypeError) as failure:
                    synth_status, synth_error = 'compile_failed', str(failure)
            if synth_status != 'ok':
                repair_payload = dict(synth_payload)
                repair_payload['previous_output'] = (
                    synth_proposal.payload_json
                    if synth_proposal.payload_json is not None else None)
                repair_payload['machine_error'] = synth_error
                repair = backend.propose(repair_task, repair_payload, schema)
                if repair.transport_status == 'SUCCESS' and repair.schema_status == 'VALID':
                    try:
                        synth_value = repair.value
                        if boundary == 'b2':
                            em.compile_b2(synth_value, inventory)
                        else:
                            em.compile_b3(synth_value['dsl'], inventory)
                        synth_status = 'ok_repaired'
                    except (ValueError, TypeError) as failure:
                        synth_status = 'synth_failed_after_repair'
                        synth_error = str(failure)
                else:
                    synth_status = 'synth_failed_after_repair'
                    synth_error = repair.error_category or repair.schema_status
        status = synth_status if synth_status else ground_status
        row = {'case_id': case.case_id, 'configuration_sha256': digest(freeze),
               'boundary': boundary,
               'ground_status': ground_status, 'synth_status': synth_status,
               'status': status if status else 'unspecified',
               'error': synth_error or ground_error,
               'prediction': {'ground': (ground_proposal.value
                                         if ground_proposal.transport_status == 'SUCCESS'
                                         else None),
                              'ground_inventory': inventory,
                              'synth': synth_value},
               'request_records': list(backend.records)}
        write_new(row_path, row)
        rows.append(row)
        print(json.dumps({'arm': 'e2e', 'boundary': boundary,
                          'completed': len(rows), 'total': len(cases),
                          'case_id': case.case_id, 'status': row['status']}),
              flush=True)
        if time.monotonic() - started > minutes * 60:
            print(json.dumps({'status': 'PARTIAL_TIME_BUDGET', 'arm': 'e2e',
                              'completed': len(rows), 'total': len(cases)}),
                  flush=True)
            return 3
    prediction_rows = [{'case_id': r['case_id'], 'prediction': r['prediction'],
                        'status': r['status'], 'boundary': r['boundary'],
                        'ground_status': r['ground_status'],
                        'synth_status': r['synth_status']} for r in rows]
    write_new(rows_path, prediction_rows)
    seal = prediction_seal(prediction_rows, [c.case_id for c in cases],
                           architecture_commit=freeze['architecture_commit'],
                           configuration_sha256=digest(freeze))
    write_new(OUT / f'{PREFIX}_e2e_prediction_seal.json', seal)
    print(json.dumps({'status': 'SEALED', 'arm': 'e2e', 'boundary': boundary,
                      'cases': len(rows),
                      'ok': sum(r['status'].startswith('ok') for r in rows)}),
          flush=True)
    return 0


# ------------------------------------------------------------------- scoring

def _hallucinate_arm(arm):
    def hallucinate(rows_by_case, cases):
        total = {'unknown_reference_attempts': 0,
                 'out_of_grammar_operator_attempts': 0,
                 'free_text_leaf_attempts': 0}
        for case in cases:
            row = rows_by_case[case.case_id]
            raw = row['prediction']
            if raw is None:
                continue
            if arm == 'b2':
                counts = em.b2_hallucination_attempts(raw, case.oracle_inventory)
            elif arm == 'b3':
                counts = grs.hallucination_attempts(raw.get('dsl', ''),
                                                    case.oracle_inventory)
            elif arm in ('e2e', 'e2ecanon'):
                synth = raw.get('synth')
                inventory = raw.get('ground_inventory') or {'facts': [], 'markers': []}
                if synth is None:
                    continue
                if row.get('boundary') == 'b2':
                    counts = em.b2_hallucination_attempts(synth, inventory)
                else:
                    counts = grs.hallucination_attempts(synth.get('dsl', ''),
                                                        inventory)
            else:
                counts = {}
            for key in total:
                total[key] += counts.get(key, 0)
        return total
    return hallucinate


def _efficiency(arm):
    records = []
    for path in sorted(OUT.glob(f'{PREFIX}_{arm}_[0-9][0-9][0-9]_request_*_result.json')):
        records.append(json.loads(path.read_text(encoding='utf-8')))
    if not records:
        return None
    latencies = [(r.get('telemetry') or {}).get('latency_ms') for r in records]
    latencies = [x / 1000 for x in latencies if isinstance(x, (int, float))]
    tokens = 0
    for r in records:
        usage = (r.get('telemetry') or {}).get('usage') or {}
        if isinstance(usage.get('total_tokens'), int):
            tokens += usage['total_tokens']
        else:
            tokens += (usage.get('prompt_tokens') or 0) \
                + (usage.get('completion_tokens') or 0)
    return {'requests': len(records), 'tokens': tokens,
            'median_latency_s': round(percentile(latencies, 50), 2) if latencies else None}




def phase_freeze_dev2() -> int:
    """Second dev freeze: the e2e-canon arm (frozen B1 synthesis prompt +
    deterministic canonicalizer over the SEALED grounder outputs), added
    after e2e(B2) dev results, BEFORE any final-holdout inference. This is
    a development-phase decision artifact only."""
    path2 = OUT / 'policy_final_v1_devfreeze2.json'
    if path2.exists():
        print(json.dumps({'status': 'DEVFREEZE2_ALREADY_DONE'}))
        return 0
    commit = _commit_clean(ROOT)
    freeze, cases = _load_devfreeze()
    ground_rows = json.loads((OUT / f'{PREFIX}_ground_predictions.json')
                             .read_text(encoding='utf-8'))
    sealed = json.loads((OUT / f'{SEALED_PREFIX}_freeze.json').read_text(encoding='utf-8'))
    freeze2 = {
        'schema_version': 'guardian-vnext-policy-final-devfreeze2-v1',
        'purpose': 'dev-phase freeze of the e2e-canon boundary (frozen B1 '
                   'synthesis prompt + deterministic canonicalizer) over the '
                   'sealed dev grounder outputs; added after e2e(B2) dev '
                   'scoring, before any final-holdout inference',
        'architecture_commit': commit,
        'b1_prompt_continuity': {
            'synth_task_sha256': digest(grs.GRS_SYNTH_TASK),
            'sealed_grs_synth_task_match': digest(grs.GRS_SYNTH_TASK)
            == sealed['grs_identity']['synth_task_sha256'],
            'repair_task_sha256': digest(grs.GRS_SYNTH_REPAIR_TASK),
            'dsl_schema_sha256': digest(grs.GRS_DSL_SCHEMA),
        },
        'canonicalizer_sha256': file_digest(
            ROOT / 'src/guardian_truth/vnext/policy_grs_emission.py'),
        'ground_predictions_sha256': digest(ground_rows),
        'ground_seal_sha256': file_digest(
            OUT / f'{PREFIX}_ground_prediction_seal.json'),
        'case_ids': freeze['case_ids'],
        'model': MODEL, 'provider': PROVIDER,
        'source_sha256': {
            'src/guardian_truth/vnext/policy_grs.py': file_digest(
                ROOT / 'src/guardian_truth/vnext/policy_grs.py'),
            'src/guardian_truth/vnext/policy_grs_emission.py': file_digest(
                ROOT / 'src/guardian_truth/vnext/policy_grs_emission.py'),
            'scripts/policy_final_grs_dev.py': file_digest(
                ROOT / 'scripts/policy_final_grs_dev.py'),
        },
    }
    write_new(path2, freeze2)
    print(json.dumps({'status': 'DEV_FROZEN2', 'architecture_commit': commit}))
    return 0


def _load_devfreeze2():
    freeze2 = json.loads((OUT / 'policy_final_v1_devfreeze2.json')
                         .read_text(encoding='utf-8'))
    for name, expected in freeze2['source_sha256'].items():
        if name == 'scripts/policy_final_grs_dev.py':
            continue  # disclosed supersession pattern (scoring fixes)
        if file_digest(ROOT / name) != expected:
            raise ValueError(f'devfreeze2 source mismatch: {name}')
    ground_rows = json.loads((OUT / f'{PREFIX}_ground_predictions.json')
                             .read_text(encoding='utf-8'))
    if freeze2['ground_predictions_sha256'] != digest(ground_rows):
        raise ValueError('ground predictions changed after devfreeze2')
    _, cases = _load_devfreeze()
    if freeze2['case_ids'] != [case.case_id for case in cases]:
        raise ValueError('devfreeze2 case identity mismatch')
    return freeze2, cases, {r['case_id']: r for r in ground_rows}


def phase_run_e2e_canon(env_file, minutes: float) -> int:
    """e2e-canon: frozen B1 synthesis prompt over the SEALED grounded
    inventories, compiled via strict-parse + deterministic canonicalizer."""
    freeze2, cases, ground_rows = _load_devfreeze2()
    if not (OUT / f'{PREFIX}_smoke.json').exists():
        print(json.dumps({'status': 'NO_SMOKE'}))
        return 2
    rows_path = OUT / f'{PREFIX}_e2ecanon_predictions.json'
    if rows_path.exists():
        print(json.dumps({'status': 'ALREADY_SEALED', 'arm': 'e2ecanon'}))
        return 0
    load_env_file(env_file)
    delegate, live = _make_delegate()
    started = time.monotonic()
    rows = []
    for index, case in enumerate(cases):
        row_path = OUT / f'{PREFIX}_e2ecanon_case_{index:03d}.json'
        if row_path.exists():
            row = json.loads(row_path.read_text(encoding='utf-8'))
            if row['case_id'] != case.case_id \
                    or row['configuration_sha256'] != digest(freeze2):
                raise ValueError('cached e2ecanon case changed')
            rows.append(row)
            continue
        ground_row = ground_rows[case.case_id]
        inventory = None
        try:
            inventory = grs_runner._postvalidate_ground(
                ground_row['prediction'], case.policy, case.atom_catalog)
        except (grs.GRSInvalid, ValueError, TypeError):
            pass
        if inventory is None:
            row = {'case_id': case.case_id,
                   'configuration_sha256': digest(freeze2),
                   'boundary': 'b1canon', 'ground_status': 'ground_failed',
                   'synth_status': None, 'status': 'ground_failed',
                   'error': ground_row.get('error'),
                   'prediction': {'ground': ground_row['prediction'],
                                  'ground_inventory': None, 'synth': None},
                   'request_records': []}
            write_new(row_path, row)
            rows.append(row)
            continue

        def compile_value(value, _inv=inventory):
            if not isinstance(value, dict) or not isinstance(value.get('dsl'), str):
                raise em.EmissionInvalid('B3_INVALID: dsl field must be a string')
            em.compile_b3(value['dsl'], _inv)

        row = _run_one_case(delegate, OUT, freeze2, index, case, live,
                            'e2ecanon', grs.GRS_SYNTH_TASK, grs.GRS_DSL_SCHEMA,
                            grs.GRS_SYNTH_REPAIR_TASK,
                            {'policy_text': case.policy, 'inventory': inventory},
                            compile_value)
        row['boundary'] = 'b1canon'
        row['ground_status'] = 'ok'
        row['synth_status'] = row['status']
        row['prediction'] = {'ground': ground_row['prediction'],
                             'ground_inventory': inventory,
                             'synth': row['prediction']}
        write_new(row_path, row)
        rows.append(row)
        print(json.dumps({'arm': 'e2ecanon', 'completed': len(rows),
                          'total': len(cases), 'case_id': case.case_id,
                          'status': row['status']}), flush=True)
        if time.monotonic() - started > minutes * 60:
            print(json.dumps({'status': 'PARTIAL_TIME_BUDGET', 'arm': 'e2ecanon',
                              'completed': len(rows), 'total': len(cases)}),
                  flush=True)
            return 3
    prediction_rows = [{'case_id': r['case_id'], 'prediction': r['prediction'],
                        'status': r['status'], 'boundary': r['boundary'],
                        'ground_status': r['ground_status'],
                        'synth_status': r['synth_status']} for r in rows]
    write_new(rows_path, prediction_rows)
    seal = prediction_seal(prediction_rows, [c.case_id for c in cases],
                           architecture_commit=freeze2['architecture_commit'],
                           configuration_sha256=digest(freeze2))
    write_new(OUT / f'{PREFIX}_e2ecanon_prediction_seal.json', seal)
    print(json.dumps({'status': 'SEALED', 'arm': 'e2ecanon', 'cases': len(rows),
                      'ok': sum(r['status'].startswith('ok') for r in rows)}),
          flush=True)
    return 0


def phase_score_dev() -> int:
    freeze, cases = _load_devfreeze()
    freeze2 = None
    if (OUT / 'policy_final_v1_devfreeze2.json').exists():
        freeze2, _, _ = _load_devfreeze2()
    h0_map = _h0_correct(cases)
    b1_rows = _load_sealed_arm('a1')

    report = {'schema_version': 'guardian-vnext-policy-final-grs-dev-v1',
              'stage': 'B_emission_refinement_development',
              'prospective_claim': None,
              'dev_emission_criteria': freeze['dev_emission_criteria'],
              'post_seal_corrections': {
                  'note': 'scoring-only fixes after all dev arms were sealed '
                          '(e2e boundary flag read from the row level, canon '
                          'summary key); predictions, seals and the dev '
                          'freeze are untouched',
                  'frozen_runner_sha256': SUPERSEDED_RUNNER_SHA256,
                  'current_runner_sha256': CURRENT_RUNNER_SHA256},
              'arms': {}}

    # sealed B1 baseline
    def compile_b1(row, case):
        prediction = row['prediction']
        if prediction is None or not isinstance(prediction.get('dsl'), str):
            return None, False
        try:
            alternatives, _ = grs.compile_dsl(prediction['dsl'],
                                              case.oracle_inventory)
            return alternatives, True
        except (grs.GRSInvalid, ValueError, TypeError):
            return None, False

    def halluc_b1(rows_by_case, cases):
        total = {'unknown_reference_attempts': 0,
                 'out_of_grammar_operator_attempts': 0,
                 'free_text_leaf_attempts': 0}
        for case in cases:
            dsl = (rows_by_case[case.case_id]['prediction'] or {}).get('dsl')
            if isinstance(dsl, str):
                counts = grs.hallucination_attempts(dsl, case.oracle_inventory)
                for key in total:
                    total[key] += counts[key]
        return total

    b1_metrics = _arm_metrics(b1_rows, cases, compile_b1, halluc_b1)
    report['arms']['B1_sealed'] = dict(b1_metrics,
                                       regression_vs_h0=_regression_stats(
                                           b1_metrics['per_case'], h0_map))

    # canon audit (B3-replay) if present
    canon_path = OUT / 'policy_final_v1_dev_canon_audit.json'
    if canon_path.exists():
        canon = json.loads(canon_path.read_text(encoding='utf-8'))
        report['arms']['B3_replay_canonicalizer'] = canon

    def _summary_entry(data):
        if 'metrics' in data and 'semantic_preservation_audit' in data:
            data = data['metrics']
        return {'validity': data.get('validity'),
                'accuracy': data.get('accuracy'),
                'hallucination': data.get('hallucination_attempts'),
                'regressions': (data.get('regression_vs_h0') or {}).get('regressions')}

    # live arms
    for arm in ('b2', 'b3', 'e2e', 'e2ecanon'):
        rows_path = OUT / f'{PREFIX}_{arm}_predictions.json'
        if not rows_path.exists():
            continue
        seal = json.loads((OUT / f'{PREFIX}_{arm}_prediction_seal.json')
                          .read_text(encoding='utf-8'))
        rows = json.loads(rows_path.read_text(encoding='utf-8'))
        if arm == 'e2ecanon' and freeze2 is None:
            raise ValueError('e2ecanon arm scored without devfreeze2')
        seal_freeze = freeze2 if arm == 'e2ecanon' else freeze
        expected = prediction_seal(rows, [c.case_id for c in cases],
                                   architecture_commit=seal_freeze['architecture_commit'],
                                   configuration_sha256=digest(seal_freeze))
        if seal != expected:
            raise ValueError(f'{arm} dev seal invalid')
        rows_by_case = {r['case_id']: r for r in rows}

        def compile_meaning(row, case, _arm=arm):
            meaning = _compile_dev_arm(_arm, row, case)
            return meaning, meaning is not None

        metrics = _arm_metrics(rows_by_case, cases, compile_meaning,
                               _hallucinate_arm(arm))
        entry = dict(metrics, regression_vs_h0=_regression_stats(
            metrics['per_case'], h0_map), efficiency=_efficiency(arm))
        if arm == 'e2e':
            grounded_ok = sum(1 for r in rows if r.get('ground_status', '').startswith('ok'))
            entry['resolved_coverage'] = round(grounded_ok / len(cases), 4)
            entry['ground_validity'] = round(grounded_ok / len(cases), 4)
            boundary, info = _selected_boundary()
            entry['boundary'] = boundary
            entry['boundary_selection_info'] = info
        if arm == 'e2ecanon':
            grounded_ok = sum(1 for r in rows if r.get('ground_status', '').startswith('ok'))
            entry['resolved_coverage'] = round(grounded_ok / len(cases), 4)
            entry['boundary'] = 'b1canon (frozen B1 prompt + canonicalizer)'
        report['arms'][arm] = entry

    # grounder-only metrics (inventory quality vs oracle)
    ground_path = OUT / f'{PREFIX}_ground_predictions.json'
    if ground_path.exists():
        rows = {r['case_id']: r for r in json.loads(ground_path.read_text(encoding='utf-8'))}
        valid_n = 0
        exact_atoms = 0
        missing_atoms = extra_atoms = 0
        for case in cases:
            row = rows[case.case_id]
            try:
                inventory = grs_runner._postvalidate_ground(
                    row['prediction'], case.policy, case.atom_catalog)
                valid_n += 1
                got = {f['atom'] for f in inventory['facts']}
                need = {f['atom'] for f in case.oracle_inventory['facts']}
                if got == need:
                    exact_atoms += 1
                missing_atoms += len(need - got)
                extra_atoms += len(got - need)
            except (grs.GRSInvalid, ValueError, TypeError):
                pass
        report['arms']['ground'] = {
            'n': len(cases), 'validity': round(valid_n / len(cases), 4),
            'exact_atom_set_rate': round(exact_atoms / len(cases), 4),
            'total_missing_atoms': missing_atoms,
            'total_extra_atoms': extra_atoms,
            'efficiency': _efficiency('ground'),
        }

    write_new(DEVREPORT_PATH, report)
    summary = {arm: _summary_entry(data) for arm, data in report['arms'].items()}
    print(json.dumps({'status': 'DEV_SCORED', 'arms': summary}, indent=1))
    return 0


def phase_status() -> int:
    arms = ['b2', 'b3', 'ground', 'e2e', 'e2ecanon']
    state = {}
    for arm in arms:
        rows = sorted(OUT.glob(f'{PREFIX}_{arm}_case_[0-9][0-9][0-9].json'))
        sealed = (OUT / f'{PREFIX}_{arm}_predictions.json').exists()
        state[arm] = {'cases': len(rows), 'sealed': sealed}
    state['canon_audit'] = (OUT / 'policy_final_v1_dev_canon_audit.json').exists()
    state['devfreeze'] = DEVFREEZE_PATH.exists()
    state['smoke'] = (OUT / f'{PREFIX}_smoke.json').exists()
    state['report'] = DEVREPORT_PATH.exists()
    print(json.dumps(state, indent=1))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase')
    parser.add_argument('--env-file', default='.env')
    parser.add_argument('--minutes', type=float, default=8.5)
    args = parser.parse_args()
    if args.phase == 'canon-audit':
        return phase_canon_audit()
    if args.phase == 'freeze-dev':
        return phase_freeze_dev()
    if args.phase == 'smoke':
        return phase_smoke(args.env_file)
    if args.phase == 'run-b2':
        return _run_synth_arm(args.env_file, args.minutes, 'b2')
    if args.phase == 'run-b3':
        return _run_synth_arm(args.env_file, args.minutes, 'b3')
    if args.phase == 'run-ground':
        return phase_run_ground(args.env_file, args.minutes)
    if args.phase == 'run-e2e':
        return phase_run_e2e(args.env_file, args.minutes)
    if args.phase == 'freeze-dev2':
        return phase_freeze_dev2()
    if args.phase == 'run-e2e-canon':
        return phase_run_e2e_canon(args.env_file, args.minutes)
    if args.phase == 'score-dev':
        return phase_score_dev()
    if args.phase == 'status':
        return phase_status()
    parser.error(f'unknown phase {args.phase}')


if __name__ == '__main__':
    raise SystemExit(main())
