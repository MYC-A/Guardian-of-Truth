"""GRS experiment: Grounded Rule Synthesis - the final standalone Policy
frontend cycle (Stage A: oracle-inventory composition ceiling; Stage B:
end-to-end grounder + synthesizer).

Preregistration: docs/vnext/GRS_PREREG_GATES_V1.json (frozen before the
first inference request of the cycle).  Phases:

  freeze-a   commit-clean check + Stage A corpus/gold freeze + H0 identity
             continuity vs the sealed PSB freeze + GRS identity freeze
  smoke-a    TWO synthetic non-benchmark requests (H0 schema, DSL schema)
  run-a0     frozen H0 parse per Stage A case (byte-identical prompts/
             schema/config; one repair re-ask), persisted, sealed
  run-a1     ONE GRS synthesis per Stage A case over the ORACLE inventory
             (one repair re-ask), persisted, sealed before gold join
  score-a    seals verified, then deterministic gold join + behavioral case
             correctness per arm + AST validity + hallucination attempt
             counters + attachment metrics + resolved coverage + exact
             McNemar vs A0 + regression gate + frozen gate evaluation
  freeze-b   requires score-a verdict PASS_STAGE_A; Stage B corpus/gold
             freeze (separate namespace, fresh 72 cases)
  smoke-b    THREE synthetic non-benchmark requests (H0, grounder, DSL)
  run-b0     frozen H0 parse per Stage B case, sealed
  run-b1     per Stage B case: grounder (1 call + repair) -> trusted
             post-validation -> synthesizer over the GROUNDER inventory
             (1 call + repair) -> validator -> compiler; grounder and
             synthesizer predictions sealed separately before gold join
  score-b    grounder metrics + synthesizer-conditional metrics +
             end-to-end metrics + unsafe permission + resolved coverage +
             exact McNemar vs B0 + regression gate + frozen gates +
             decomposition analysis (A1 ceiling vs B1)
  audit      deterministic post-seal failure taxonomy (no LLM judge)

Models never see gold: A1/B1 inputs are the policy text and (oracle or
grounder) inventory only.  Never start concurrently with another API job.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import subprocess
import sys
import time

from guardian_truth.llm_client import ChatClient, ClientConfig
from guardian_truth.runtime import provider_config
from guardian_truth.settings import load_env_file
from guardian_truth.vnext.experiment import PersistedSemanticBackend, ProviderPause
from guardian_truth.vnext.integrity import (digest, file_digest, prediction_seal,
                                            write_new, verify_files)
from guardian_truth.vnext.latency import percentile
from guardian_truth.vnext.semantic_v2 import DiagnosticSemanticBackend

from guardian_truth.vnext import policy_v3_benchmark as v3
from guardian_truth.vnext import policy_grs as grs
from guardian_truth.vnext import policy_grs_causal_benchmark as corpus_a
from guardian_truth.vnext import policy_grs_prospective_benchmark as corpus_b
from guardian_truth.vnext import policy_psb as psb

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evaluate_vnext_c_alr_reimpl import (PARSE_TASK, REPAIR_TASK,  # noqa: E402
                                         STRUCTURE_SCHEMA, CONFIG,
                                         mcnemar_exact_p, newcombe_paired_ci)

ROOT = Path(__file__).resolve().parents[1]
PREFIX_A = 'policy_grs_stage_a_v1'
PREFIX_B = 'policy_grs_stage_b_v1'
PREREG_DOC = 'docs/vnext/GRS_PREREG_GATES_V1.json'
PSB_FREEZE_PATH = 'outputs/vnext/policy_psb_causal_v1_freeze.json'

SOURCES = [
    'src/guardian_truth/vnext/policy_grs.py',
    'src/guardian_truth/vnext/policy_grs_causal_benchmark.py',
    'src/guardian_truth/vnext/policy_grs_prospective_benchmark.py',
    'src/guardian_truth/vnext/policy_psb.py',
    'src/guardian_truth/vnext/policy_v3_benchmark.py',
    'scripts/evaluate_vnext_c_alr_reimpl.py',
    'scripts/evaluate_vnext_policy_grs.py',
]

GRS_GATES = {
    "stage_a": {
        "a1_behavioral_gte": 0.85,
        "a1_ast_validity_gte": 0.95,
        "a1_capacity_subset_gte": 0.75,
        "a1_nl_stress_gte": 0.75,
        "a1_h0_correct_regression_rate_lte": 0.10,
        "a1_minus_a0_pp_gte": 0.10,
    },
    "stage_b": {
        "b1_behavioral_gte": 0.85,
        "b1_simple_subset_gte": 0.95,
        "b1_structural_subset_gte": 0.80,
        "b1_capacity_subset_gte": 0.70,
        "b1_nl_stress_gte": 0.75,
        "b1_unsafe_permission_rate_lte": 0.02,
        "b1_resolved_coverage_gte": 0.75,
        "b1_ast_validity_gte": 0.95,
        "b1_h0_correct_regression_rate_lte": 0.10,
        "unsupported_semantic_leaf_rate_eq": 0,
    },
}

H0_IDENTITY = {
    'parse_task_sha256': digest(PARSE_TASK),
    'repair_task_sha256': digest(REPAIR_TASK),
    'structure_schema_sha256': digest(STRUCTURE_SCHEMA),
    'definition': CONFIG,
    'definition_sha256': digest(CONFIG),
    'system_instruction': 'guardian_truth.vnext.semantic.SYSTEM (persisted per request)',
    'input_contract': "payload {'policy_text': str, 'atom_catalog': [str]}",
    'repair_rule': 'exactly one machine-validation-triggered repair re-ask '
                   '(transport failure / schema invalid / compile failure); '
                   'never for schema-valid wrong answers',
    'retry_policy': 'client max_retries=0; no invisible retries; abandoned '
                    'request captures are never resent',
    'behavioral_evaluator': 'grs.grs_score_prediction over compiled program '
                            'alternatives (psb.composed_verdict over v3 '
                            'programs); H0: single flat program',
    'case_correct_definition': 'every compiled alternative composes a verdict '
                               'on EVERY frozen world that belongs to the '
                               'acceptable set (composed verdicts of the '
                               'admissible gold program sets); H0: the single '
                               'flat program must do so',
}

GRS_IDENTITY = {
    'synth_task_sha256': digest(grs.GRS_SYNTH_TASK),
    'synth_repair_task_sha256': digest(grs.GRS_SYNTH_REPAIR_TASK),
    'dsl_schema_sha256': digest(grs.GRS_DSL_SCHEMA),
    'ground_task_sha256': digest(grs.GRS_GROUND_TASK),
    'ground_repair_task_sha256': digest(grs.GRS_GROUND_REPAIR_TASK),
    'ground_schema_sha256': digest(grs.GRS_GROUND_SCHEMA),
    'representation': 'small typed DSL ruleset (frozen grammar in the task '
                      'prompt; refs are neutral inventory fact IDs; '
                      'ONE_OF local ambiguity; UNKNOWN_* abstention gates)',
    'core_invariant': 'every semantic leaf references an inventory fact ID; '
                      'markers are never rule references; unsupported '
                      'semantic leaf rate in compiled programs = 0 by '
                      'construction',
    'compiler': 'grs.compile_dsl -> v3 program alternatives with field parity '
                'to the frozen PSB compiler',
    'validator': 'grs.validate_ruleset_ast: deterministic reject-only type '
                 'checks; no semantic repair',
    'grounder_role': 'atoms ONLY from the supplied atom catalog with exact '
                     'spans; no roles or attachments; UNKNOWN abstention',
}

SMOKE_POLICY_H0 = 'Night porters may use the goods stairwell when the lift is serviced.'
SMOKE_CATALOG_H0 = ['action:use_goods_stairwell', 'state:lift_serviced',
                    'distractor:smoke_case']
SMOKE_POLICY_SYNTH = 'If the netting loft is warm, falconers may weigh the young kestrels.'
SMOKE_INVENTORY_SYNTH = {'facts': [
    {'id': 'F1', 'kind': 'ACTION', 'atom': 'action:weigh_the_young_kestrels',
     'span': 'weigh the young kestrels'},
    {'id': 'F2', 'kind': 'STATE', 'atom': 'state:netting_loft_warm',
     'span': 'the netting loft is warm'},
    {'id': 'F3', 'kind': 'ACTOR', 'atom': 'actor:falconer', 'span': 'falconers'}],
    'markers': [
    {'id': 'M1', 'kind': 'MODAL_MARKER', 'value': 'PERMIT', 'span': 'may'},
    {'id': 'R1', 'kind': 'RELATION_MARKER', 'value': 'IF', 'span': 'If'}]}
SMOKE_POLICY_GROUND = 'The duty ringer may polish the handbells before the tower tour.'
SMOKE_CATALOG_GROUND = ['action:polish_the_handbells', 'event:tower_tour',
                        'actor:duty_ringer', 'distractor:smoke_case']


# ------------------------------------------------------------------ statistics

def wilson_ci(k: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = k / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - margin) / denom, (centre + margin) / denom


# --------------------------------------------------------------------- freeze

def _case_inputs(cases):
    return [{'case_id': case.case_id, 'policy': case.policy,
             'atom_catalog': list(case.atom_catalog),
             'inventory': case.oracle_inventory} for case in cases]


def _load_prereg(root: Path) -> dict:
    prereg = json.loads((root / PREREG_DOC).read_text(encoding='utf-8'))
    if prereg['stage_a']['gates'] != GRS_GATES['stage_a'] \
            or prereg['stage_b']['gates'] != GRS_GATES['stage_b']:
        raise ValueError('runner gates differ from the preregistered gates')
    return prereg


def _commit_clean(root: Path) -> str:
    if subprocess.run(['git', 'diff', '--quiet', 'HEAD', '--', *SOURCES], cwd=root).returncode:
        raise ValueError('commit study implementation before freeze')
    for name in SOURCES:
        if subprocess.run(['git', 'ls-files', '--error-unmatch', name], cwd=root,
                          capture_output=True).returncode:
            raise ValueError('all frozen study sources must be tracked')
    return subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root, capture_output=True,
                          text=True, check=True).stdout.strip()


def _h0_continuity(root: Path) -> dict:
    psb_path = root / PSB_FREEZE_PATH
    psb_freeze = json.loads(psb_path.read_text(encoding='utf-8'))
    continuity = {
        'psb_freeze_path': PSB_FREEZE_PATH,
        'psb_freeze_sha256': file_digest(psb_path),
        'psb_architecture_commit': psb_freeze['architecture_commit'],
        'parse_task_match': digest(PARSE_TASK) == psb_freeze['h0_identity']['parse_task_sha256'],
        'repair_task_match': digest(REPAIR_TASK) == psb_freeze['h0_identity']['repair_task_sha256'],
        'structure_schema_match': digest(STRUCTURE_SCHEMA) == psb_freeze['h0_identity']['structure_schema_sha256'],
        'definition_match': digest(CONFIG) == psb_freeze['h0_identity']['definition_sha256'],
    }
    for key in ('parse_task_match', 'repair_task_match', 'structure_schema_match',
                'definition_match'):
        if not continuity[key]:
            raise ValueError(f'H0 identity drift: {key} failed - H0 may not change')
    return continuity


def phase_freeze_a(root: Path, out: Path) -> int:
    freeze_path = out / f'{PREFIX_A}_freeze.json'
    bench_path = out / f'{PREFIX_A}_benchmark.json'
    if freeze_path.exists():
        raise FileExistsError('stage A freeze already exists')
    prereg = _load_prereg(root)
    if prereg['stage_a']['composition'] != corpus_a.COHORT_PLAN:
        raise ValueError('preregistered Stage A corpus composition mismatch')
    if prereg['stage_a']['benchmark'] != 'NEW causal corpus, 56 cases, gold by construction; not PSB corpus, not PHV1 corpus; frozen before predictions':
        raise ValueError('preregistered Stage A benchmark description mismatch')
    cases = corpus_a.build_grs_stage_a_benchmark()
    if len(cases) != 56:
        raise ValueError('preregistered Stage A corpus size mismatch')
    document = corpus_a.benchmark_grs_stage_a_document(cases)
    commit = _commit_clean(root)
    write_new(bench_path, document)
    write_new(freeze_path, {'schema_version': 'guardian-vnext-grs-freeze-a-v1',
                            'study': 'GRS_V1',
                            'stage': 'A',
                            'prereg': PREREG_DOC,
                            'architecture_commit': commit,
                            'h0_identity': H0_IDENTITY,
                            'h0_continuity': _h0_continuity(root),
                            'grs_identity': GRS_IDENTITY,
                            'definition': CONFIG, 'definition_sha256': digest(CONFIG),
                            'gates': GRS_GATES,
                            'prereg_sha256': file_digest(root / PREREG_DOC),
                            'case_ids': [case.case_id for case in cases],
                            'case_input_sha256': digest(_case_inputs(cases)),
                            'benchmark_sha256': file_digest(bench_path),
                            'gold_dsl_sha256': digest(
                                {case.case_id: case.gold_dsl for case in cases}),
                            'gold_inventory_sha256': digest(
                                {case.case_id: case.oracle_inventory for case in cases}),
                            'gold_frozen_before_predictions': True,
                            'gold_joined': False,
                            'source_sha256': {name: file_digest(root / name) for name in SOURCES},
                            'prompt_hash_policy': 'exact payload/messages/schema persisted '
                                                  'before every physical request',
                            'frozen_utc': datetime.now(timezone.utc).isoformat()})
    print(json.dumps({'status': 'FROZEN_NOT_RUN', 'stage': 'A', 'cases': len(cases),
                      'commit': commit[:8], 'h0_continuity': 'VERIFIED',
                      'capacity': sum(not case.h0_representable for case in cases)}))
    return 0


def _load_freeze(root: Path, out: Path, prefix: str, corpus, plan: dict, size: int):
    freeze = json.loads((out / f'{prefix}_freeze.json').read_text(encoding='utf-8'))
    bench = json.loads((out / f'{prefix}_benchmark.json').read_text(encoding='utf-8'))
    if freeze['definition_sha256'] != digest(CONFIG) or freeze['gates'] != GRS_GATES \
            or freeze['h0_identity'] != H0_IDENTITY or freeze['grs_identity'] != GRS_IDENTITY:
        raise ValueError('frozen study configuration mismatch')
    if freeze['benchmark_sha256'] != file_digest(out / f'{prefix}_benchmark.json'):
        raise ValueError('benchmark storage hash mismatch')
    if freeze['prereg_sha256'] != file_digest(root / PREREG_DOC):
        raise ValueError('preregistration edited after freeze')
    cases = []
    for row in bench['cases']:
        case = corpus.PolicyGRSCase(
            case_id=row['case_id'], cohort=row['cohort'], style=row['style'],
            policy=row['policy'], atom_catalog=tuple(row['atom_catalog']),
            oracle_inventory=row['oracle_inventory'], gold_dsl=row['gold_dsl'],
            admissible_program_sets=tuple(tuple(dict(p) for p in s)
                                          for s in row['admissible_program_sets']),
            worlds=tuple(dict(w) for w in row['worlds']),
            axes=tuple(row.get('axes', ())),
            h0_representable=row['h0_representable'])
        cases.append(case)
    if freeze['case_ids'] != [case.case_id for case in cases]:
        raise ValueError('frozen case identity mismatch')
    if freeze['case_input_sha256'] != digest(_case_inputs(cases)):
        raise ValueError('case inputs changed after freeze')
    if freeze.get('gold_dsl_sha256') != digest(
            {case.case_id: case.gold_dsl for case in cases}):
        raise ValueError('gold DSL changed after freeze')
    if freeze.get('gold_inventory_sha256') != digest(
            {case.case_id: case.oracle_inventory for case in cases}):
        raise ValueError('gold inventories changed after freeze')
    if plan != {cohort: sum(1 for case in cases if case.cohort == cohort)
                for cohort in plan} or len(cases) != size:
        raise ValueError('frozen corpus composition mismatch')
    failures = verify_files(root, freeze['source_sha256'])
    if failures:
        raise ValueError(f'frozen source mismatch: {failures}')
    return freeze, cases


def load_freeze_a(root: Path, out: Path):
    return _load_freeze(root, out, PREFIX_A, corpus_a, corpus_a.COHORT_PLAN, 56)


def load_freeze_b(root: Path, out: Path):
    return _load_freeze(root, out, PREFIX_B, corpus_b, corpus_b.COHORT_PLAN_B, 72)


# ---------------------------------------------------------------------- smoke

def _make_delegate():
    config = provider_config(ClientConfig(timeout_seconds=180, max_output_tokens=2048,
                                          max_retries=0, response_format_mode='none'),
                             'bai', model='qwen3.8-flash')
    live: list = []
    delegate = DiagnosticSemanticBackend(ChatClient(config), interval_seconds=10,
                                        checkpoint=live.append)
    return delegate, live


def _smoke_common(delegate, out: Path, freeze: dict, prefix: str, live: list):
    backend = PersistedSemanticBackend(delegate, out, f'{prefix}_smoke',
                                       configuration_sha256=digest(freeze),
                                       live_records=live)
    h0 = backend.propose(PARSE_TASK,
                         {'policy_text': SMOKE_POLICY_H0,
                          'atom_catalog': SMOKE_CATALOG_H0},
                         STRUCTURE_SCHEMA)
    synth = backend.propose(grs.GRS_SYNTH_TASK,
                            {'policy_text': SMOKE_POLICY_SYNTH,
                             'inventory': SMOKE_INVENTORY_SYNTH},
                            grs.GRS_DSL_SCHEMA)
    return h0, synth, backend


def phase_smoke_a(env_file, root: Path, out: Path) -> int:
    freeze, _cases = load_freeze_a(root, out)
    smoke_path = out / f'{PREFIX_A}_smoke.json'
    if smoke_path.exists():
        print(json.dumps({'status': 'SMOKE_ALREADY_DONE'}))
        return 0
    load_env_file(env_file)
    delegate, live = _make_delegate()
    h0, synth, backend = _smoke_common(delegate, out, freeze, PREFIX_A, live)
    smoke = {'schema_version': 'guardian-vnext-grs-smoke-a-v1',
             'purpose': 'synthetic non-benchmark schema/provider smoke BEFORE '
                        'the first semantic request (one H0 schema request, '
                        'one DSL synthesis request)',
             'payloads_are_benchmark_cases': False,
             'scored': False,
             'h0': {'transport_status': h0.transport_status,
                    'schema_status': h0.schema_status,
                    'error_category': h0.error_category},
             'synth': {'transport_status': synth.transport_status,
                       'schema_status': synth.schema_status,
                       'error_category': synth.error_category},
             'telemetry': [dict(record) for record in backend.records]}
    write_new(smoke_path, smoke)
    if h0.transport_status != 'SUCCESS' or synth.transport_status != 'SUCCESS':
        print(json.dumps({'status': 'SMOKE_TRANSPORT_FAILED'}))
        return 2
    print(json.dumps({'status': 'SMOKE_OK', 'h0_schema': h0.schema_status,
                      'synth_schema': synth.schema_status}))
    return 0


def phase_smoke_b(env_file, root: Path, out: Path) -> int:
    freeze, _cases = load_freeze_b(root, out)
    smoke_path = out / f'{PREFIX_B}_smoke.json'
    if smoke_path.exists():
        print(json.dumps({'status': 'SMOKE_ALREADY_DONE'}))
        return 0
    load_env_file(env_file)
    delegate, live = _make_delegate()
    backend = PersistedSemanticBackend(delegate, out, f'{PREFIX_B}_smoke',
                                       configuration_sha256=digest(freeze),
                                       live_records=live)
    h0 = backend.propose(PARSE_TASK,
                         {'policy_text': SMOKE_POLICY_H0,
                          'atom_catalog': SMOKE_CATALOG_H0},
                         STRUCTURE_SCHEMA)
    ground = backend.propose(grs.GRS_GROUND_TASK,
                             {'policy_text': SMOKE_POLICY_GROUND,
                              'atom_catalog': SMOKE_CATALOG_GROUND},
                             grs.GRS_GROUND_SCHEMA)
    synth = backend.propose(grs.GRS_SYNTH_TASK,
                            {'policy_text': SMOKE_POLICY_SYNTH,
                             'inventory': SMOKE_INVENTORY_SYNTH},
                            grs.GRS_DSL_SCHEMA)
    smoke = {'schema_version': 'guardian-vnext-grs-smoke-b-v1',
             'purpose': 'synthetic non-benchmark schema/provider smoke BEFORE '
                        'the first Stage B semantic request (H0, grounder, DSL)',
             'payloads_are_benchmark_cases': False,
             'scored': False,
             'h0': {'transport_status': h0.transport_status,
                    'schema_status': h0.schema_status},
             'ground': {'transport_status': ground.transport_status,
                        'schema_status': ground.schema_status},
             'synth': {'transport_status': synth.transport_status,
                       'schema_status': synth.schema_status},
             'telemetry': [dict(record) for record in backend.records]}
    write_new(smoke_path, smoke)
    if any(status != 'SUCCESS' for status in
           (h0.transport_status, ground.transport_status, synth.transport_status)):
        print(json.dumps({'status': 'SMOKE_TRANSPORT_FAILED'}))
        return 2
    print(json.dumps({'status': 'SMOKE_OK', 'h0_schema': h0.schema_status,
                      'ground_schema': ground.schema_status,
                      'synth_schema': synth.schema_status}))
    return 0


# ------------------------------------------------------------------- run arms

def _h0_compile(value):
    v3.compile_v3_structure(value)


def _run_single_arm_case(delegate, out: Path, freeze: dict, index: int, case,
                         live: list, arm: str, task: str, schema: dict,
                         payload: dict, repair_task: str, compile_value):
    """One case for one single-call arm: primary request + at most one frozen
    repair re-ask.  Deterministic order, persisted per request."""
    stem = f'{PREFIX_A}_{arm}_{index:03d}' if arm in ('a0', 'a1') \
        else f'{PREFIX_B}_{arm}_{index:03d}'
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
            compile_value(value)
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
                compile_value(value)
                status, error = 'ok_repaired', None
            except (ValueError, TypeError) as failure:
                status, error = 'compile_failed_after_repair', str(failure)
        elif status == 'parse_failed':
            status = 'parse_failed_after_repair'
            error = repair.error_category or repair.schema_status
    return {'case_id': case.case_id, 'configuration_sha256': digest(freeze),
            'status': status, 'error': error, 'prediction': value,
            'request_records': records}


def _run_arm(env_file, root: Path, out: Path, minutes: float, arm: str,
             load_freeze, smoke_prefix: str) -> int:
    freeze, cases = load_freeze(root, out)
    if not (out / f'{smoke_prefix}_smoke.json').exists():
        print(json.dumps({'status': 'NO_SMOKE', 'note': 'run the smoke phase first'}))
        return 2
    prefix = PREFIX_A if arm in ('a0', 'a1') else PREFIX_B
    rows_path = out / f'{prefix}_{arm}_predictions.json'
    if rows_path.exists():
        print(json.dumps({'status': 'ALREADY_SEALED', 'arm': arm}))
        return 0
    if arm == 'a0' or arm == 'b0':
        task, schema, repair_task = PARSE_TASK, STRUCTURE_SCHEMA, REPAIR_TASK
    else:
        task, schema, repair_task = (grs.GRS_SYNTH_TASK, grs.GRS_DSL_SCHEMA,
                                     grs.GRS_SYNTH_REPAIR_TASK)
    load_env_file(env_file)
    delegate, live = _make_delegate()
    started = time.monotonic()
    rows = []
    for index, case in enumerate(cases):
        row_path = out / f'{prefix}_{arm}_case_{index:03d}.json'
        if row_path.exists():
            row = json.loads(row_path.read_text(encoding='utf-8'))
            if row['case_id'] != case.case_id or row['configuration_sha256'] != digest(freeze):
                raise ValueError(f'cached {arm} case changed')
        else:
            if arm in ('a0', 'b0'):
                payload = {'policy_text': case.policy,
                           'atom_catalog': list(case.atom_catalog)}
                compile_value = _h0_compile
            else:
                payload = {'policy_text': case.policy,
                           'inventory': case.oracle_inventory}
                def compile_value(value, _case=case):
                    if not isinstance(value, dict) or not isinstance(value.get('dsl'), str):
                        raise grs.GRSInvalid('DSL_INVALID: dsl field must be a string')
                    grs.compile_dsl(value['dsl'], _case.oracle_inventory)
            try:
                row = _run_single_arm_case(delegate, out, freeze, index, case,
                                           live, arm, task, schema, payload,
                                           repair_task, compile_value)
            except ProviderPause as error:
                print(json.dumps({'status': 'PROVIDER_PAUSED', 'reason': str(error),
                                  'arm': arm, 'completed': len(rows),
                                  'total': len(cases)}), flush=True)
                return 2
            write_new(row_path, row)
        rows.append(row)
        print(json.dumps({'arm': arm, 'completed': len(rows), 'total': len(cases),
                          'case_id': case.case_id, 'status': row['status']}), flush=True)
        if time.monotonic() - started > minutes * 60:
            print(json.dumps({'status': 'PARTIAL_TIME_BUDGET', 'arm': arm,
                              'completed': len(rows), 'total': len(cases)}), flush=True)
            return 3
    prediction_rows = [{'case_id': row['case_id'], 'prediction': row['prediction'],
                        'status': row['status']} for row in rows]
    write_new(rows_path, prediction_rows)
    seal = prediction_seal(prediction_rows, [case.case_id for case in cases],
                           architecture_commit=freeze['architecture_commit'],
                           configuration_sha256=digest(freeze))
    write_new(out / f'{prefix}_{arm}_prediction_seal.json', seal)
    print(json.dumps({'status': 'SEALED', 'arm': arm, 'cases': len(rows),
                      'ok': sum(row['status'].startswith('ok') for row in rows)}),
          flush=True)
    return 0


def phase_run_a0(env_file, root: Path, out: Path, minutes: float) -> int:
    return _run_arm(env_file, root, out, minutes, 'a0', load_freeze_a, PREFIX_A)


def phase_run_a1(env_file, root: Path, out: Path, minutes: float) -> int:
    return _run_arm(env_file, root, out, minutes, 'a1', load_freeze_a, PREFIX_A)


def phase_run_b0(env_file, root: Path, out: Path, minutes: float) -> int:
    return _run_arm(env_file, root, out, minutes, 'b0', load_freeze_b, PREFIX_B)


# ------------------------------------------------------------- grounder (B1)

def _postvalidate_ground(value, policy_text: str, atom_catalog) -> dict:
    """Trusted deterministic post-validation of a grounder proposal:
    atoms ONLY from the catalog, spans exact substrings, neutral unique IDs,
    frozen marker enums, no role fields.  Returns the normalized inventory
    (fact kinds derived from atom prefixes).  Raises GRSInvalid otherwise."""
    if not isinstance(value, dict) or set(value) != {'facts', 'markers'}:
        raise grs.GRSInvalid('GROUND_INVALID: output must have facts and markers')
    catalog = set(atom_catalog)
    seen_ids: set = set()
    atoms: set = set()
    fact_rows = []
    if not isinstance(value['facts'], list):
        raise grs.GRSInvalid('GROUND_INVALID: facts must be an array')
    for fact in value['facts']:
        if not isinstance(fact, dict) or set(fact) != {'id', 'atom', 'span'}:
            raise grs.GRSInvalid('GROUND_INVALID: fact fields must be exactly '
                                 'id, atom, span')
        fid, atom, span = fact['id'], fact['atom'], fact['span']
        if not isinstance(fid, str) or not grs._FACT_ID_RE.fullmatch(fid):
            raise grs.GRSInvalid(f"GROUND_INVALID: fact id {fid!r} must be F#")
        if fid in seen_ids:
            raise grs.GRSInvalid(f'GROUND_INVALID: duplicate id {fid!r}')
        seen_ids.add(fid)
        if not isinstance(atom, str) or atom not in catalog:
            raise grs.GRSInvalid(f'INVENTORY: atom {atom!r} is not in '
                                 'ATOM_CATALOG (invented atoms are rejected)')
        if atom in atoms:
            raise grs.GRSInvalid(f'GROUND_INVALID: duplicate atom {atom!r}')
        atoms.add(atom)
        if not isinstance(span, str) or span not in policy_text:
            raise grs.GRSInvalid(f'GROUND_INVALID: span for {fid} is not an '
                                 'exact substring of POLICY_TEXT')
        kind = grs._kind_of_atom(atom)
        if kind is None:
            raise grs.GRSInvalid(f'GROUND_INVALID: untyped atom {atom!r}')
        fact_rows.append({'id': fid, 'kind': kind, 'atom': atom, 'span': span})
    marker_rows = []
    if not isinstance(value['markers'], list):
        raise grs.GRSInvalid('GROUND_INVALID: markers must be an array')
    for marker in value['markers']:
        if not isinstance(marker, dict) or set(marker) != {'id', 'kind', 'value', 'span'}:
            raise grs.GRSInvalid('GROUND_INVALID: marker fields must be exactly '
                                 'id, kind, value, span')
        mid, kind, mval, span = (marker['id'], marker['kind'],
                                 marker['value'], marker['span'])
        if not isinstance(mid, str) or not grs._MARKER_ID_RE.fullmatch(mid):
            raise grs.GRSInvalid(f'GROUND_INVALID: marker id {mid!r} must be '
                                 'M# or R#')
        if mid in seen_ids:
            raise grs.GRSInvalid(f'GROUND_INVALID: duplicate id {mid!r}')
        seen_ids.add(mid)
        expected_kind = 'MODAL_MARKER' if mid.startswith('M') else 'RELATION_MARKER'
        if kind != expected_kind:
            raise grs.GRSInvalid(f'GROUND_INVALID: marker id {mid!r} must '
                                 f'have kind {expected_kind}')
        allowed = (grs.MODAL_MARKER_VALUES if kind == 'MODAL_MARKER'
                   else grs.RELATION_MARKER_VALUES)
        if mval not in allowed:
            raise grs.GRSInvalid(f'GROUND_INVALID: marker value {mval!r} '
                                 f'not in {allowed}')
        if not isinstance(span, str) or span not in policy_text:
            raise grs.GRSInvalid(f'GROUND_INVALID: span for {mid} is not an '
                                 'exact substring of POLICY_TEXT')
        marker_rows.append({'id': mid, 'kind': kind, 'value': mval, 'span': span})
    return {'facts': fact_rows, 'markers': marker_rows}


def _run_b1_case(delegate, out: Path, freeze: dict, index: int, case, live: list):
    """One Stage B case: grounder (1 call + repair) -> trusted post-validation
    -> synthesizer over the GROUNDER inventory (1 call + repair)."""
    stem = f'{PREFIX_B}_b1_{index:03d}'
    backend = PersistedSemanticBackend(delegate, out, stem,
                                        configuration_sha256=digest(freeze),
                                        live_records=live)
    ground_payload = {'policy_text': case.policy,
                      'atom_catalog': list(case.atom_catalog)}
    proposal = backend.propose(grs.GRS_GROUND_TASK, ground_payload, grs.GRS_GROUND_SCHEMA)
    ground_status, ground_error, inventory = None, None, None
    if proposal.transport_status != 'SUCCESS' or proposal.schema_status != 'VALID':
        ground_status = 'parse_failed'
        ground_error = proposal.error_category or proposal.schema_status
    else:
        try:
            inventory = _postvalidate_ground(proposal.value, case.policy,
                                             case.atom_catalog)
            ground_status = 'ok'
        except (grs.GRSInvalid, ValueError, TypeError) as failure:
            ground_status, ground_error = 'ground_invalid', str(failure)
    if ground_status != 'ok':
        repair_payload = dict(ground_payload)
        repair_payload['previous_output'] = (proposal.payload_json
                                             if proposal.payload_json is not None else None)
        repair_payload['machine_error'] = ground_error
        repair = backend.propose(grs.GRS_GROUND_REPAIR_TASK, repair_payload,
                                 grs.GRS_GROUND_SCHEMA)
        if repair.transport_status == 'SUCCESS' and repair.schema_status == 'VALID':
            try:
                inventory = _postvalidate_ground(repair.value, case.policy,
                                                 case.atom_catalog)
                ground_status = 'ok_repaired'
            except (grs.GRSInvalid, ValueError, TypeError) as failure:
                ground_status = 'ground_invalid_after_repair'
                ground_error = str(failure)
        elif ground_status == 'parse_failed':
            ground_status = 'parse_failed_after_repair'
            ground_error = repair.error_category or repair.schema_status
    ground_prediction = (repair.value if ground_status == 'ok_repaired'
                         else proposal.value)
    if ground_status in ('ok', 'ok_repaired'):
        synth_payload = {'policy_text': case.policy, 'inventory': inventory}
        synth = backend.propose(grs.GRS_SYNTH_TASK, synth_payload, grs.GRS_DSL_SCHEMA)
        status, error, value = None, None, None
        if synth.transport_status != 'SUCCESS' or synth.schema_status != 'VALID':
            status = 'parse_failed'
            error = synth.error_category or synth.schema_status
        else:
            value = synth.value
            try:
                if not isinstance(value, dict) or not isinstance(value.get('dsl'), str):
                    raise grs.GRSInvalid('DSL_INVALID: dsl field must be a string')
                grs.compile_dsl(value['dsl'], inventory)
                status = 'ok'
            except (grs.GRSInvalid, ValueError, TypeError) as failure:
                status, error = 'compile_failed', str(failure)
        if status != 'ok':
            repair_payload = dict(synth_payload)
            repair_payload['previous_output'] = (synth.payload_json
                                                 if synth.payload_json is not None else None)
            repair_payload['machine_error'] = error
            synth_repair = backend.propose(grs.GRS_SYNTH_REPAIR_TASK, repair_payload,
                                           grs.GRS_DSL_SCHEMA)
            if synth_repair.transport_status == 'SUCCESS' \
                    and synth_repair.schema_status == 'VALID':
                try:
                    value = synth_repair.value
                    if not isinstance(value, dict) or not isinstance(value.get('dsl'), str):
                        raise grs.GRSInvalid('DSL_INVALID: dsl field must be a string')
                    grs.compile_dsl(value['dsl'], inventory)
                    status = 'ok_repaired'
                except (grs.GRSInvalid, ValueError, TypeError) as failure:
                    status, error = 'compile_failed_after_repair', str(failure)
            elif status == 'parse_failed':
                status = 'parse_failed_after_repair'
                error = synth_repair.error_category or synth_repair.schema_status
    else:
        value, status, error = None, 'ground_failed', ground_error
    return {'case_id': case.case_id, 'configuration_sha256': digest(freeze),
            'ground_status': ground_status, 'ground_error': ground_error,
            'ground_prediction': ground_prediction,
            'inventory_used': inventory,
            'status': status, 'error': error, 'prediction': value,
            'request_records': list(backend.records)}


def phase_run_b1(env_file, root: Path, out: Path, minutes: float) -> int:
    freeze, cases = load_freeze_b(root, out)
    if not (out / f'{PREFIX_B}_smoke.json').exists():
        print(json.dumps({'status': 'NO_SMOKE', 'note': 'run the smoke phase first'}))
        return 2
    rows_path = out / f'{PREFIX_B}_b1_predictions.json'
    if rows_path.exists():
        print(json.dumps({'status': 'ALREADY_SEALED', 'arm': 'b1'}))
        return 0
    load_env_file(env_file)
    delegate, live = _make_delegate()
    started = time.monotonic()
    rows = []
    for index, case in enumerate(cases):
        row_path = out / f'{PREFIX_B}_b1_case_{index:03d}.json'
        if row_path.exists():
            row = json.loads(row_path.read_text(encoding='utf-8'))
            if row['case_id'] != case.case_id or row['configuration_sha256'] != digest(freeze):
                raise ValueError('cached b1 case changed')
        else:
            try:
                row = _run_b1_case(delegate, out, freeze, index, case, live)
            except ProviderPause as error:
                print(json.dumps({'status': 'PROVIDER_PAUSED', 'reason': str(error),
                                  'arm': 'b1', 'completed': len(rows),
                                  'total': len(cases)}), flush=True)
                return 2
            write_new(row_path, row)
        rows.append(row)
        print(json.dumps({'arm': 'b1', 'completed': len(rows), 'total': len(cases),
                          'case_id': case.case_id, 'status': row['status'],
                          'ground': row['ground_status']}), flush=True)
        if time.monotonic() - started > minutes * 60:
            print(json.dumps({'status': 'PARTIAL_TIME_BUDGET', 'arm': 'b1',
                              'completed': len(rows), 'total': len(cases)}), flush=True)
            return 3
    ground_rows = [{'case_id': row['case_id'], 'prediction': row['ground_prediction'],
                    'status': row['ground_status']} for row in rows]
    write_new(out / f'{PREFIX_B}_ground_predictions.json', ground_rows)
    seal = prediction_seal(ground_rows, [case.case_id for case in cases],
                           architecture_commit=freeze['architecture_commit'],
                           configuration_sha256=digest(freeze))
    write_new(out / f'{PREFIX_B}_ground_prediction_seal.json', seal)
    prediction_rows = [{'case_id': row['case_id'], 'prediction': row['prediction'],
                        'status': row['status']} for row in rows]
    write_new(rows_path, prediction_rows)
    seal = prediction_seal(prediction_rows, [case.case_id for case in cases],
                           architecture_commit=freeze['architecture_commit'],
                           configuration_sha256=digest(freeze))
    write_new(out / f'{PREFIX_B}_b1_prediction_seal.json', seal)
    print(json.dumps({'status': 'SEALED', 'arm': 'b1', 'cases': len(rows),
                      'ok': sum(row['status'].startswith('ok') for row in rows),
                      'ground_ok': sum(row['ground_status'].startswith('ok')
                                       for row in rows)}), flush=True)
    return 0


# --------------------------------------------------------------------- scoring

def _load_sealed(out: Path, prefix: str, arm: str, freeze: dict, case_ids):
    rows = json.loads((out / f'{prefix}_{arm}_predictions.json').read_text(encoding='utf-8'))
    seal = json.loads((out / f'{prefix}_{arm}_prediction_seal.json').read_text(encoding='utf-8'))
    expected = prediction_seal(rows, case_ids,
                               architecture_commit=freeze['architecture_commit'],
                               configuration_sha256=digest(freeze))
    if seal != expected:
        raise ValueError(f'{arm} prediction seal invalid; gold was not opened before seal')
    return {row['case_id']: row for row in rows}


def _h0_programs(row):
    prediction = row['prediction']
    if prediction is None:
        return None, False
    try:
        return [v3.compile_v3_structure(dict(prediction))], True
    except (v3.StructureInvalid, ValueError, TypeError):
        return None, False


def _grs_alternatives(row, inventory):
    """Compile a sealed DSL prediction against the given (oracle or grounder)
    inventory.  Returns (alternatives, dropped, valid)."""
    prediction = row['prediction']
    if prediction is None or not isinstance(prediction.get('dsl'), str):
        return None, [], False
    try:
        alternatives, dropped = grs.compile_dsl(prediction['dsl'], inventory)
        return alternatives, dropped, True
    except (grs.GRSInvalid, ValueError, TypeError):
        return None, [], False


def _score_case(case, programs_or_alternatives, is_grs: bool):
    if is_grs:
        if programs_or_alternatives is None:
            return False, None
        return grs.grs_score_prediction(programs_or_alternatives, case.worlds,
                                        case.admissible_program_sets)
    if programs_or_alternatives is None:
        return False, None
    return psb.score_program_set(programs_or_alternatives, case.worlds,
                                 case.admissible_program_sets)


def _unsafe_permission(per_world) -> bool:
    for world in per_world or []:
        verdicts = world.get('verdicts') or [world.get('verdict')]
        if any(v == 'PERMITTED' for v in verdicts) \
                and 'PERMITTED' not in world.get('acceptable', []):
            return True
    return False


def _accuracy(cases, per_case, arm, subset=None):
    members = [case for case in cases if subset is None or subset(case)]
    k = sum(per_case[arm][case.case_id]['correct'] for case in members)
    return {'n': len(members), 'correct': k,
            'accuracy': round(k / len(members), 4) if members else None}


def _paired(a_results, b_results, cases):
    corrections = sum(1 for case in cases
                      if not b_results[case.case_id]['correct']
                      and a_results[case.case_id]['correct'])
    regressions = sum(1 for case in cases
                      if b_results[case.case_id]['correct']
                      and not a_results[case.case_id]['correct'])
    return corrections, regressions


def _gold_triples(case):
    triples = set()
    for program in case.admissible_program_sets[0]:
        triples |= psb.canonical_triples_flat(program)
    return triples


def _arm_triples_h0(programs):
    if not programs:
        return set()
    return psb.canonical_triples_flat(programs[0])


def _arm_triples_grs(alternatives):
    if not alternatives:
        return set()
    triples = set()
    for program in alternatives[0]:
        triples |= psb.canonical_triples_flat(program)
    return triples


def _hallucination_totals(rows_by_case, cases, inventory_of, out=None,
                          prefix=None, arm=None):
    """Deterministic attempt counters over EVERY persisted proposal output of
    the arm (primary, repair and failed attempts alike; compiled programs are
    guaranteed clean by the validator - these count rejected attempts)."""
    totals = {'unknown_reference_attempts': 0,
              'out_of_grammar_operator_attempts': 0,
              'free_text_leaf_attempts': 0,
              'cases_with_attempts': 0}
    examples = []
    for case in cases:
        row = rows_by_case[case.case_id]
        dsl_texts = []
        prediction = row['prediction']
        if prediction is not None and isinstance(prediction.get('dsl'), str):
            dsl_texts.append(prediction['dsl'])
        if out is not None and prefix is not None and arm is not None:
            index = [c.case_id for c in cases].index(case.case_id)
            for result_path in sorted(out.glob(
                    f'{prefix}_{arm}_{index:03d}_request_*_result.json')):
                artifact = json.loads(result_path.read_text(encoding='utf-8'))
                payload_json = (artifact.get('proposal') or {}).get('payload_json')
                if payload_json is None:
                    continue
                try:
                    value = json.loads(payload_json)
                except ValueError:
                    continue
                if isinstance(value, dict) and isinstance(value.get('dsl'), str):
                    dsl_texts.append(value['dsl'])
        case_counts = None
        for dsl_text in dsl_texts:
            counts = grs.hallucination_attempts(dsl_text, inventory_of(case))
            if case_counts is None:
                case_counts = counts
            else:
                for key in ('unknown_reference_attempts',
                            'out_of_grammar_operator_attempts',
                            'free_text_leaf_attempts'):
                    case_counts[key] += counts[key]
        if case_counts is None:
            continue
        if any(case_counts[key] for key in
               ('unknown_reference_attempts', 'out_of_grammar_operator_attempts',
                'free_text_leaf_attempts')):
            totals['cases_with_attempts'] += 1
            examples.append({'case_id': case.case_id, **{
                key: case_counts[key] for key in case_counts
                if key.endswith('examples')}})
        for key in list(totals)[:3]:
            totals[key] += case_counts[key]
    totals['examples'] = examples[:12]
    return totals


def _efficiency(out: Path, prefix: str, arm: str, n: int):
    tokens, latencies, repairs = 0, [], 0
    for index in range(n):
        row_path = out / f'{prefix}_{arm}_case_{index:03d}.json'
        row = json.loads(row_path.read_text(encoding='utf-8')) if row_path.exists() else {}
        for record in row.get('request_records', []):
            tokens += record.get('usage', {}).get('total_tokens', 0)
            if record.get('latency_ms'):
                latencies.append(float(record['latency_ms']))
    requests = len(latencies)
    return {'requests': requests, 'requests_per_case': round(requests / n, 3) if n else None,
            'total_tokens': tokens, 'tokens_per_case': round(tokens / n, 1) if n else None,
            'repair_requests': max(0, requests - n),
            'repair_rate': round(max(0, requests - n) / n, 4) if n else None,
            'median_latency_ms': percentile(latencies, .5) if latencies else None,
            'p95_latency_ms': percentile(latencies, .95) if latencies else None}


STRUCTURAL_COHORTS = ('condition', 'exception', 'condition_plus_exception',
                      'if_vs_only_if', 'modality', 'scope_togetherness',
                      'separate_clauses_modalities', 'per_clause_actors',
                      'temporal', 'provenance_identity', 'negation',
                      'multi_axis', 'nl_prose_stress')


def phase_score_a(root: Path, out: Path) -> int:
    freeze, cases = load_freeze_a(root, out)
    n = len(cases)
    rows_h0 = _load_sealed(out, PREFIX_A, 'a0', freeze, [c.case_id for c in cases])
    rows_a1 = _load_sealed(out, PREFIX_A, 'a1', freeze, [c.case_id for c in cases])
    per_case = {'a0': {}, 'a1': {}}
    arms_state = {'a0': {}, 'a1': {}}
    for case in cases:
        programs, valid = _h0_programs(rows_h0[case.case_id])
        correct, per_world = _score_case(case, programs, False)
        arms_state['a0'][case.case_id] = {'programs': programs, 'valid': valid}
        per_case['a0'][case.case_id] = {'correct': correct, 'per_world': per_world,
                                        'status': rows_h0[case.case_id]['status']}
        alternatives, dropped, valid = _grs_alternatives(
            rows_a1[case.case_id], case.oracle_inventory)
        correct, per_world = _score_case(case, alternatives, True)
        arms_state['a1'][case.case_id] = {'alternatives': alternatives,
                                          'dropped': dropped, 'valid': valid}
        per_case['a1'][case.case_id] = {'correct': correct, 'per_world': per_world,
                                        'status': rows_a1[case.case_id]['status'],
                                        'resolved': bool(valid and not dropped)}
    behavioral = {arm: _accuracy(cases, per_case, arm) for arm in per_case}
    validity = {arm: sum(1 for case in cases
                         if per_case[arm][case.case_id]['status'].startswith('ok')) / n
                for arm in per_case}
    resolved_coverage = sum(per_case['a1'][case.case_id]['resolved'] for case in cases) / n
    unknown_drop_cases = [case.case_id for case in cases if arms_state['a1'][case.case_id]['dropped']]
    cohort_metrics = {arm: {cohort: _accuracy(cases, per_case, arm,
                                              lambda c, co=cohort: c.cohort == co)
                            for cohort in sorted({c.cohort for c in cases})}
                      for arm in per_case}
    capacity = {arm: _accuracy(cases, per_case, arm,
                               lambda c: not c.h0_representable) for arm in per_case}
    representable = {arm: _accuracy(cases, per_case, arm,
                                    lambda c: c.h0_representable) for arm in per_case}
    structural = {arm: _accuracy(cases, per_case, arm,
                                 lambda c: c.cohort in STRUCTURAL_COHORTS) for arm in per_case}
    nl_stress = {arm: _accuracy(cases, per_case, arm,
                                lambda c: c.cohort == 'nl_prose_stress') for arm in per_case}
    unsafe = {'a0': 0, 'a1': 0}
    for arm in per_case:
        for case in cases:
            if _unsafe_permission(per_case[arm][case.case_id]['per_world']):
                unsafe[arm] += 1
    hallucination = _hallucination_totals(rows_a1, cases,
                                         lambda c: c.oracle_inventory,
                                         out=out, prefix=PREFIX_A, arm='a1')
    gold_triples = {case.case_id: _gold_triples(case) for case in cases}
    h0_triples = {case.case_id: _arm_triples_h0(arms_state['a0'][case.case_id]['programs'])
                  for case in cases}
    a1_triples = {case.case_id: _arm_triples_grs(arms_state['a1'][case.case_id]['alternatives'])
                  for case in cases}
    binding = {'a0_flat_projection': psb.binding_metrics(h0_triples, gold_triples),
               'a1_compiled': psb.binding_metrics(a1_triples, gold_triples)}
    corrections, regressions = _paired(per_case['a1'], per_case['a0'], cases)
    delta = behavioral['a1']['accuracy'] - behavioral['a0']['accuracy']
    ci = newcombe_paired_ci(corrections, regressions, n)
    pairs = {'a1_vs_a0': {'corrections': corrections, 'regressions': regressions,
                          'delta_accuracy': round(delta, 4),
                          'newcombe_paired_ci95_delta': [round(ci[0], 4), round(ci[1], 4)],
                          'mcnemar_exact_p_two_sided': round(
                              mcnemar_exact_p(corrections, regressions), 6),
                          'correction_precision': (corrections / (corrections + regressions))
                          if corrections + regressions else None}}
    h0_correct = [case for case in cases if per_case['a0'][case.case_id]['correct']]
    regression_gate = {'n_h0_correct': len(h0_correct),
                       'wrong': sum(1 for case in h0_correct
                                    if not per_case['a1'][case.case_id]['correct']),
                       'rate': round(sum(1 for case in h0_correct
                                         if not per_case['a1'][case.case_id]['correct'])
                                     / len(h0_correct), 4) if h0_correct else None}
    gates = GRS_GATES['stage_a']
    structural_delta = structural['a1']['accuracy'] - structural['a0']['accuracy']
    gate_eval = {
        'a1_behavioral': behavioral['a1']['accuracy'],
        'behavioral_pass': behavioral['a1']['accuracy'] >= gates['a1_behavioral_gte'],
        'a1_ast_validity': round(validity['a1'], 4),
        'validity_pass': validity['a1'] >= gates['a1_ast_validity_gte'],
        'a1_capacity': capacity['a1']['accuracy'],
        'capacity_pass': capacity['a1']['accuracy'] is not None
        and capacity['a1']['accuracy'] >= gates['a1_capacity_subset_gte'],
        'a1_nl_stress': nl_stress['a1']['accuracy'],
        'nl_pass': nl_stress['a1']['accuracy'] is not None
        and nl_stress['a1']['accuracy'] >= gates['a1_nl_stress_gte'],
        'regression_rate': regression_gate['rate'],
        'regression_pass': regression_gate['rate'] is not None
        and regression_gate['rate'] <= gates['a1_h0_correct_regression_rate_lte'],
        'delta_overall': round(delta, 4),
        'delta_structural': round(structural_delta, 4),
        'delta_pass': delta >= gates['a1_minus_a0_pp_gte']
        or structural_delta >= gates['a1_minus_a0_pp_gte'],
        'resolved_coverage': round(resolved_coverage, 4),
        'unsupported_semantic_leaf_rate_in_compiled_programs': 0,
    }
    gate_eval['all_pass'] = all(gate_eval[key] for key in
                                ('behavioral_pass', 'validity_pass', 'capacity_pass',
                                 'nl_pass', 'regression_pass', 'delta_pass'))
    verdict = 'PASS_STAGE_A' if gate_eval['all_pass'] else 'REJECT_GRS_COMPOSITION'
    efficiency = {arm: _efficiency(out, PREFIX_A, arm, n) for arm in ('a0', 'a1')}
    report = {'schema_version': 'guardian-vnext-grs-results-a-v1',
              'experiment': 'GRS_V1', 'stage': 'A',
              'prereg': PREREG_DOC,
              'architecture_commit': freeze['architecture_commit'],
              'freeze_sha256': file_digest(out / f'{PREFIX_A}_freeze.json'),
              'benchmark_sha256': freeze['benchmark_sha256'],
              'case_count': n,
              'arms': {'a0': 'frozen flat single-structure H0 (byte-identical chain)',
                       'a1': 'oracle-inventory GRS synthesis (diagnostic ceiling, '
                             'NOT deployable)'},
              'primary_metric': {arm: {'correct': behavioral[arm]['correct'], 'n': n,
                                       'accuracy': behavioral[arm]['accuracy'],
                                       'wilson_ci95': [round(v, 4) for v in
                                                       wilson_ci(behavioral[arm]['correct'], n)]}
                                 for arm in behavioral},
              'validity': {arm: round(validity[arm], 4) for arm in validity},
              'resolved_coverage_a1': round(resolved_coverage, 4),
              'unknown_drop_cases': unknown_drop_cases,
              'cohorts': cohort_metrics,
              'structural_subset': structural,
              'capacity_subset': capacity,
              'h0_representable_subset': representable,
              'nl_stress_subset': nl_stress,
              'unsafe_permission_cases': unsafe,
              'hallucination_attempts': hallucination,
              'binding_attachment': binding,
              'paired_statistics': pairs,
              'regression_gate': regression_gate,
              'gates_evaluation': {'evaluation': gate_eval, 'gates': gates},
              'verdict': verdict,
              'efficiency': efficiency,
              'research_questions': {
                  'Q1_composition_ceiling': behavioral['a1']['accuracy'],
                  'Q2_closed_vocabulary_zero_unsupported_leaves': True,
                  'Q3_dsl_validity_vs_psb_graph_0841': round(validity['a1'], 4),
                  'Q4_attachment_micro_f1': binding['a1_compiled']['aggregate']['f1'],
                  'Q5_capacity_accuracy': capacity['a1']['accuracy'],
                  'Q6_bottleneck': 'NOT_TESTED_STAGE_A_ONLY (A1 - B1 after Stage B)',
                  'Q7_regression_rate': regression_gate['rate'],
                  'Q8_unknown_gaming': {'resolved_coverage': round(resolved_coverage, 4),
                                        'unknown_drop_cases': len(unknown_drop_cases)},
                  'Q9_cost': efficiency,
                  'Q10_integration': 'decided by Stage B'}}
    results_path = out / f'{PREFIX_A}_results.json'
    if results_path.exists():
        existing = json.loads(results_path.read_text(encoding='utf-8'))
        if digest(existing) != digest(report):
            raise ValueError('stage A results changed on recompute')
    else:
        write_new(results_path, report)
    print(json.dumps({'experiment': 'GRS_V1_STAGE_A',
                      'a0': behavioral['a0']['accuracy'],
                      'a1': behavioral['a1']['accuracy'],
                      'a1_validity': round(validity['a1'], 4),
                      'capacity_a1': capacity['a1']['accuracy'],
                      'nl_a1': nl_stress['a1']['accuracy'],
                      'regression_rate': regression_gate['rate'],
                      'resolved_coverage': round(resolved_coverage, 4),
                      'mcnemar_p': pairs['a1_vs_a0']['mcnemar_exact_p_two_sided'],
                      'verdict': verdict}), flush=True)
    return 0


def phase_freeze_b(root: Path, out: Path) -> int:
    freeze_path = out / f'{PREFIX_B}_freeze.json'
    bench_path = out / f'{PREFIX_B}_benchmark.json'
    if freeze_path.exists():
        raise FileExistsError('stage B freeze already exists')
    results_path = out / f'{PREFIX_A}_results.json'
    results = json.loads(results_path.read_text(encoding='utf-8'))
    if results['verdict'] != 'PASS_STAGE_A':
        raise ValueError(f'Stage B refused: Stage A verdict is '
                         f'{results["verdict"]} (required PASS_STAGE_A)')
    prereg = _load_prereg(root)
    if prereg['stage_b']['composition'] != corpus_b.COHORT_PLAN_B:
        raise ValueError('preregistered Stage B corpus composition mismatch')
    cases = corpus_b.build_grs_stage_b_benchmark()
    if len(cases) != 72:
        raise ValueError('preregistered Stage B corpus size mismatch')
    document = corpus_b.benchmark_grs_stage_b_document(cases)
    commit = _commit_clean(root)
    write_new(bench_path, document)
    write_new(freeze_path, {'schema_version': 'guardian-vnext-grs-freeze-b-v1',
                            'study': 'GRS_V1',
                            'stage': 'B',
                            'prereg': PREREG_DOC,
                            'architecture_commit': commit,
                            'h0_identity': H0_IDENTITY,
                            'h0_continuity': _h0_continuity(root),
                            'grs_identity': GRS_IDENTITY,
                            'definition': CONFIG, 'definition_sha256': digest(CONFIG),
                            'gates': GRS_GATES,
                            'prereg_sha256': file_digest(root / PREREG_DOC),
                            'stage_a_results_sha256': file_digest(results_path),
                            'stage_a_verdict': results['verdict'],
                            'case_ids': [case.case_id for case in cases],
                            'case_input_sha256': digest(_case_inputs(cases)),
                            'benchmark_sha256': file_digest(bench_path),
                            'gold_dsl_sha256': digest(
                                {case.case_id: case.gold_dsl for case in cases}),
                            'gold_inventory_sha256': digest(
                                {case.case_id: case.oracle_inventory for case in cases}),
                            'gold_frozen_before_predictions': True,
                            'gold_joined': False,
                            'source_sha256': {name: file_digest(root / name) for name in SOURCES},
                            'prompt_hash_policy': 'exact payload/messages/schema persisted '
                                                  'before every physical request',
                            'frozen_utc': datetime.now(timezone.utc).isoformat()})
    print(json.dumps({'status': 'FROZEN_NOT_RUN', 'stage': 'B', 'cases': len(cases),
                      'commit': commit[:8], 'stage_a_verdict': results['verdict'],
                      'capacity': sum(not case.h0_representable for case in cases)}))
    return 0


def _gold_needed_atoms(case) -> set:
    atoms = set()
    for program in case.admissible_program_sets[0]:
        for clause in program['target_clauses']:
            atoms.update(clause)
        for lit in program['condition_literals'] + program['exception_literals']:
            atoms.add(lit[1:] if lit.startswith('!') else lit)
    return atoms


def _gold_inventory_atoms(case) -> set:
    return {fact['atom'] for fact in case.oracle_inventory['facts']}


def phase_score_b(root: Path, out: Path) -> int:
    freeze, cases = load_freeze_b(root, out)
    n = len(cases)
    rows_b0 = _load_sealed(out, PREFIX_B, 'b0', freeze, [c.case_id for c in cases])
    rows_ground = _load_sealed(out, PREFIX_B, 'ground', freeze, [c.case_id for c in cases])
    rows_b1 = _load_sealed(out, PREFIX_B, 'b1', freeze, [c.case_id for c in cases])
    per_case = {'b0': {}, 'b1': {}}
    ground_state = {}
    for case in cases:
        programs, valid = _h0_programs(rows_b0[case.case_id])
        correct, per_world = _score_case(case, programs, False)
        per_case['b0'][case.case_id] = {'correct': correct, 'per_world': per_world,
                                        'status': rows_b0[case.case_id]['status']}
        ground_row = rows_ground[case.case_id]
        inventory = None
        if ground_row['status'].startswith('ok'):
            inventory = _postvalidate_ground(ground_row['prediction'], case.policy,
                                             case.atom_catalog)
        alternatives, dropped, valid = (None, [], False)
        if inventory is not None:
            alternatives, dropped, valid = _grs_alternatives(rows_b1[case.case_id],
                                                             inventory)
        correct, per_world = _score_case(case, alternatives, True)
        ground_state[case.case_id] = {
            'inventory': inventory, 'ground_status': ground_row['status'],
            'extracted_atoms': sorted({f['atom'] for f in inventory['facts']})
            if inventory else [],
            'needed': _gold_needed_atoms(case),
            'gold_atoms': _gold_inventory_atoms(case)}
        per_case['b1'][case.case_id] = {'correct': correct, 'per_world': per_world,
                                        'status': rows_b1[case.case_id]['status'],
                                        'resolved': bool(valid and not dropped
                                                         and inventory is not None)}
    behavioral = {arm: _accuracy(cases, per_case, arm) for arm in per_case}
    validity = {arm: sum(1 for case in cases
                         if per_case[arm][case.case_id]['status'].startswith('ok')) / n
                for arm in per_case}
    resolved_coverage = sum(per_case['b1'][case.case_id]['resolved'] for case in cases) / n
    cohort_metrics = {arm: {cohort: _accuracy(cases, per_case, arm,
                                              lambda c, co=cohort: c.cohort == co)
                            for cohort in sorted({c.cohort for c in cases})}
                      for arm in per_case}
    capacity = {arm: _accuracy(cases, per_case, arm,
                               lambda c: not c.h0_representable) for arm in per_case}
    simple = {arm: _accuracy(cases, per_case, arm,
                             lambda c: c.cohort == 'simple_controls') for arm in per_case}
    structural = {arm: _accuracy(cases, per_case, arm,
                                 lambda c: c.cohort in STRUCTURAL_COHORTS) for arm in per_case}
    nl_stress = {arm: _accuracy(cases, per_case, arm,
                                lambda c: c.cohort == 'nl_prose_stress') for arm in per_case}
    unsafe = {arm: sum(1 for case in cases
                       if _unsafe_permission(per_case[arm][case.case_id]['per_world']))
              for arm in per_case}
    # grounder metrics (deterministic gold join)
    grounder = {'atom_precision': None, 'atom_recall': None, 'needed_atom_recall': None,
                'marker_precision': None, 'marker_recall': None,
                'invented_atom_attempt_cases': 0, 'span_validity_after_repair': 1.0,
                'ground_validity': sum(1 for case in cases
                                       if ground_state[case.case_id]['ground_status']
                                       .startswith('ok')) / n,
                'missed_needed_atoms_total': 0, 'wrong_atoms_total': 0}
    extracted_n = gold_n = overlap_n = needed_n = needed_overlap_n = 0
    gold_marker_n = extracted_marker_n = marker_overlap_n = 0
    for case in cases:
        state = ground_state[case.case_id]
        extracted, needed, gold_atoms = (set(state['extracted_atoms']),
                                         state['needed'], state['gold_atoms'])
        extracted_n += len(extracted)
        gold_n += len(gold_atoms)
        overlap_n += len(extracted & gold_atoms)
        needed_n += len(needed)
        needed_overlap_n += len(needed & extracted)
        grounder['missed_needed_atoms_total'] += len(needed - extracted)
        grounder['wrong_atoms_total'] += len(extracted - gold_atoms)
        gold_markers = {(m['kind'], m['value']) for m in case.oracle_inventory['markers']}
        if state['inventory'] is not None:
            extracted_markers = {(m['kind'], m['value'])
                                 for m in state['inventory']['markers']}
        else:
            extracted_markers = set()
        gold_marker_n += len(gold_markers)
        extracted_marker_n += len(extracted_markers)
        marker_overlap_n += len(extracted_markers & gold_markers)
    for index in range(n):
        row_path = out / f'{PREFIX_B}_b1_case_{index:03d}.json'
        row = json.loads(row_path.read_text(encoding='utf-8')) if row_path.exists() else {}
        if 'is not in ATOM_CATALOG' in (row.get('ground_error') or ''):
            grounder['invented_atom_attempt_cases'] += 1
    grounder['atom_precision'] = round(overlap_n / extracted_n, 4) if extracted_n else None
    grounder['atom_recall'] = round(overlap_n / gold_n, 4) if gold_n else None
    grounder['needed_atom_recall'] = round(needed_overlap_n / needed_n, 4) if needed_n else None
    grounder['marker_precision'] = round(marker_overlap_n / extracted_marker_n, 4) \
        if extracted_marker_n else None
    grounder['marker_recall'] = round(marker_overlap_n / gold_marker_n, 4) if gold_marker_n else None
    # synthesizer-conditional metrics
    sufficient_clean = [case for case in cases
                        if ground_state[case.case_id]['needed']
                        <= set(ground_state[case.case_id]['extracted_atoms'])
                        and set(ground_state[case.case_id]['extracted_atoms'])
                        <= ground_state[case.case_id]['gold_atoms']]
    conditional = {'n': len(sufficient_clean),
                   'correct': sum(per_case['b1'][case.case_id]['correct']
                                  for case in sufficient_clean),
                   'accuracy': round(sum(per_case['b1'][case.case_id]['correct']
                                         for case in sufficient_clean)
                                     / len(sufficient_clean), 4)
                   if sufficient_clean else None}
    hallucination = _hallucination_totals(
        rows_b1, cases,
        lambda c: ground_state[c.case_id]['inventory'] or {'facts': [], 'markers': []},
        out=out, prefix=PREFIX_B, arm='b1')
    gold_triples = {case.case_id: _gold_triples(case) for case in cases}
    b0_triples = {case.case_id: _arm_triples_h0(
        _h0_programs(rows_b0[case.case_id])[0]) for case in cases}
    b1_alternatives = {}
    for case in cases:
        state = ground_state[case.case_id]
        if state['inventory'] is not None:
            b1_alternatives[case.case_id] = _grs_alternatives(rows_b1[case.case_id],
                                                              state['inventory'])[0]
        else:
            b1_alternatives[case.case_id] = None
    b1_triples = {case.case_id: _arm_triples_grs(b1_alternatives[case.case_id])
                  for case in cases}
    binding = {'b0_flat_projection': psb.binding_metrics(b0_triples, gold_triples),
               'b1_compiled': psb.binding_metrics(b1_triples, gold_triples)}
    corrections, regressions = _paired(per_case['b1'], per_case['b0'], cases)
    delta = behavioral['b1']['accuracy'] - behavioral['b0']['accuracy']
    ci = newcombe_paired_ci(corrections, regressions, n)
    pairs = {'b1_vs_b0': {'corrections': corrections, 'regressions': regressions,
                          'delta_accuracy': round(delta, 4),
                          'newcombe_paired_ci95_delta': [round(ci[0], 4), round(ci[1], 4)],
                          'mcnemar_exact_p_two_sided': round(
                              mcnemar_exact_p(corrections, regressions), 6),
                          'correction_precision': (corrections / (corrections + regressions))
                          if corrections + regressions else None}}
    b0_correct = [case for case in cases if per_case['b0'][case.case_id]['correct']]
    regression_gate = {'n_h0_correct': len(b0_correct),
                       'wrong': sum(1 for case in b0_correct
                                    if not per_case['b1'][case.case_id]['correct']),
                       'rate': round(sum(1 for case in b0_correct
                                         if not per_case['b1'][case.case_id]['correct'])
                                     / len(b0_correct), 4) if b0_correct else None}
    gates = GRS_GATES['stage_b']
    gate_eval = {
        'b1_behavioral': behavioral['b1']['accuracy'],
        'behavioral_pass': behavioral['b1']['accuracy'] >= gates['b1_behavioral_gte'],
        'b1_simple': simple['b1']['accuracy'],
        'simple_pass': simple['b1']['accuracy'] is not None
        and simple['b1']['accuracy'] >= gates['b1_simple_subset_gte'],
        'b1_structural': structural['b1']['accuracy'],
        'structural_pass': structural['b1']['accuracy'] is not None
        and structural['b1']['accuracy'] >= gates['b1_structural_subset_gte'],
        'b1_capacity': capacity['b1']['accuracy'],
        'capacity_pass': capacity['b1']['accuracy'] is not None
        and capacity['b1']['accuracy'] >= gates['b1_capacity_subset_gte'],
        'b1_nl_stress': nl_stress['b1']['accuracy'],
        'nl_pass': nl_stress['b1']['accuracy'] is not None
        and nl_stress['b1']['accuracy'] >= gates['b1_nl_stress_gte'],
        'unsafe_permission_rate': round(unsafe['b1'] / n, 4),
        'unsafe_permission_pass': unsafe['b1'] / n <= gates['b1_unsafe_permission_rate_lte'],
        'resolved_coverage': round(resolved_coverage, 4),
        'resolved_coverage_pass': resolved_coverage >= gates['b1_resolved_coverage_gte'],
        'b1_ast_validity': round(validity['b1'], 4),
        'validity_pass': validity['b1'] >= gates['b1_ast_validity_gte'],
        'regression_rate': regression_gate['rate'],
        'regression_pass': regression_gate['rate'] is not None
        and regression_gate['rate'] <= gates['b1_h0_correct_regression_rate_lte'],
        'unsupported_semantic_leaf_rate_in_compiled_programs': 0,
        'unsupported_leaf_pass': True,
    }
    gate_eval['all_pass'] = all(gate_eval[key] for key in
                                ('behavioral_pass', 'simple_pass', 'structural_pass',
                                 'capacity_pass', 'nl_pass', 'unsafe_permission_pass',
                                 'resolved_coverage_pass', 'validity_pass',
                                 'regression_pass', 'unsupported_leaf_pass'))
    verdict = ('PROMOTE_GRS_TO_INTEGRATION' if gate_eval['all_pass']
               else 'GRS_GROUNDING_BOTTLENECK')
    stage_a_results = json.loads((out / f'{PREFIX_A}_results.json').read_text(encoding='utf-8'))
    a1_accuracy = stage_a_results['primary_metric']['a1']['accuracy']
    efficiency = {'b0': _efficiency(out, PREFIX_B, 'b0', n),
                  'b1': _efficiency(out, PREFIX_B, 'b1', n)}
    report = {'schema_version': 'guardian-vnext-grs-results-b-v1',
              'experiment': 'GRS_V1', 'stage': 'B',
              'prereg': PREREG_DOC,
              'architecture_commit': freeze['architecture_commit'],
              'freeze_sha256': file_digest(out / f'{PREFIX_B}_freeze.json'),
              'benchmark_sha256': freeze['benchmark_sha256'],
              'stage_a_verdict': freeze['stage_a_verdict'],
              'case_count': n,
              'arms': {'b0': 'frozen flat single-structure H0 (byte-identical chain)',
                       'b1': 'end-to-end GRS: grounder -> inventory -> frozen '
                             'synthesizer -> validator -> compiler'},
              'primary_metric': {arm: {'correct': behavioral[arm]['correct'], 'n': n,
                                       'accuracy': behavioral[arm]['accuracy'],
                                       'wilson_ci95': [round(v, 4) for v in
                                                       wilson_ci(behavioral[arm]['correct'], n)]}
                                 for arm in behavioral},
              'validity': {arm: round(validity[arm], 4) for arm in validity},
              'resolved_coverage_b1': round(resolved_coverage, 4),
              'cohorts': cohort_metrics,
              'simple_subset': simple,
              'structural_subset': structural,
              'capacity_subset': capacity,
              'nl_stress_subset': nl_stress,
              'unsafe_permission_cases': unsafe,
              'unsafe_permission_rate': {'b0': round(unsafe['b0'] / n, 4),
                                         'b1': round(unsafe['b1'] / n, 4)},
              'hallucination_attempts': hallucination,
              'binding_attachment': binding,
              'grounder_metrics': grounder,
              'synthesizer_conditional_on_sufficient_clean_inventory': conditional,
              'decomposition': {
                  'a1_oracle_ceiling': a1_accuracy,
                  'b1_end_to_end': behavioral['b1']['accuracy'],
                  'grounding_cost_pp': round(a1_accuracy - behavioral['b1']['accuracy'], 4),
                  'interpretation': 'A1 - B1 isolates the grounding stage; the '
                                   'conditional metric isolates composition under '
                                   'sufficient+clean inventories'},
              'paired_statistics': pairs,
              'regression_gate': regression_gate,
              'gates_evaluation': {'evaluation': gate_eval, 'gates': gates},
              'verdict': verdict,
              'efficiency': efficiency,
              'research_questions': {
                  'Q1_composition_ceiling': a1_accuracy,
                  'Q2_closed_vocabulary_zero_unsupported_leaves': True,
                  'Q3_dsl_validity': round(validity['b1'], 4),
                  'Q4_attachment_micro_f1': binding['b1_compiled']['aggregate']['f1'],
                  'Q5_capacity_accuracy': capacity['b1']['accuracy'],
                  'Q6_bottleneck': {'grounding_cost_pp':
                                    round(a1_accuracy - behavioral['b1']['accuracy'], 4),
                                    'conditional_on_good_inventory': conditional['accuracy'],
                                    'grounder_needed_atom_recall':
                                    grounder['needed_atom_recall']},
                  'Q7_regression_rate': regression_gate['rate'],
                  'Q8_unknown_gaming': {'resolved_coverage': round(resolved_coverage, 4)},
                  'Q9_cost': efficiency,
                  'Q10_integration': verdict == 'PROMOTE_GRS_TO_INTEGRATION'}}
    results_path = out / f'{PREFIX_B}_results.json'
    if results_path.exists():
        existing = json.loads(results_path.read_text(encoding='utf-8'))
        if digest(existing) != digest(report):
            raise ValueError('stage B results changed on recompute')
    else:
        write_new(results_path, report)
    print(json.dumps({'experiment': 'GRS_V1_STAGE_B',
                      'b0': behavioral['b0']['accuracy'],
                      'b1': behavioral['b1']['accuracy'],
                      'a1_ceiling': a1_accuracy,
                      'conditional_b1': conditional['accuracy'],
                      'grounder_atom_recall': grounder['atom_recall'],
                      'needed_recall': grounder['needed_atom_recall'],
                      'b1_validity': round(validity['b1'], 4),
                      'simple_b1': simple['b1']['accuracy'],
                      'capacity_b1': capacity['b1']['accuracy'],
                      'nl_b1': nl_stress['b1']['accuracy'],
                      'unsafe_perm_b1': round(unsafe['b1'] / n, 4),
                      'resolved_coverage': round(resolved_coverage, 4),
                      'regression_rate': regression_gate['rate'],
                      'mcnemar_p': pairs['b1_vs_b0']['mcnemar_exact_p_two_sided'],
                      'verdict': verdict}), flush=True)
    return 0


def _ground_error(rows_ground, case_id):
    return rows_ground[case_id].get('error') or ''


# ---------------------------------------------------------------------- audit

_PRIORITY = ('MODALITY_ERROR', 'ATTACHMENT_ERROR', 'CONDITION_EXCEPTION_ERROR',
             'SCOPE_ERROR', 'TEMPORAL_ERROR', 'ACTOR_ERROR', 'MULTI_CLAUSE_ERROR',
             'OTHER')


def _diff_label(pred_programs, gold_programs):
    """Deterministic composition-diff labels between the predicted program
    list and the closest gold program list (no LLM judge)."""
    if pred_programs is None:
        return ['REPRESENTATION_GAP']
    diffs: set = set()
    def targets(programs):
        return [frozenset().union(*[frozenset(c) for c in p['target_clauses']])
                for p in programs]
    pred_t, gold_t = targets(pred_programs), targets(gold_programs)
    if len(pred_programs) != len(gold_programs):
        diffs.add('MULTI_CLAUSE_ERROR')
    used = set()
    for gi, gtarget in enumerate(gold_t):
        best, best_overlap = None, -1
        for pi, ptarget in enumerate(pred_t):
            if pi in used:
                continue
            overlap = len(gtarget & ptarget)
            if overlap > best_overlap:
                best, best_overlap = pi, overlap
        if best is None or best_overlap == 0:
            diffs.add('MULTI_CLAUSE_ERROR')
            continue
        used.add(best)
        pred, gold = pred_programs[best], gold_programs[gi]
        if pred['modality'] != gold['modality']:
            diffs.add('MODALITY_ERROR')
        if pred['relation'] != gold['relation']:
            diffs.add('CONDITION_EXCEPTION_ERROR')
        pc, pe = set(pred['condition_literals']), set(pred['exception_literals'])
        gc, ge = set(gold['condition_literals']), set(gold['exception_literals'])
        if (pc | pe) != (gc | ge) or pc != gc:
            diffs.add('CONDITION_EXCEPTION_ERROR')
        if pred['temporal'] != gold['temporal']:
            diffs.add('TEMPORAL_ERROR')
        pa = {l for l in pc if l.startswith('actor:')}
        ga = {l for l in gc if l.startswith('actor:')}
        if pa != ga:
            diffs.add('ACTOR_ERROR')
        if sorted(map(sorted, pred['target_clauses'])) != sorted(map(sorted, gold['target_clauses'])):
            diffs.add('SCOPE_ERROR')
    for pi in range(len(pred_t)):
        if pi not in used and any(pred_t[pi] & g for g in gold_t):
            diffs.add('ATTACHMENT_ERROR')
        elif pi not in used:
            diffs.add('MULTI_CLAUSE_ERROR')
    if not diffs:
        diffs.add('OTHER')
    return sorted(diffs, key=_PRIORITY.index)


def _classify_arm_case(case, row, arm, compiled, valid, ground_state=None):
    status = row['status']
    if not status.startswith('ok'):
        if status.startswith('parse_failed'):
            return 'REPRESENTATION_GAP'
        error = row.get('error') or ''
        if error.startswith('UNKNOWN_REFERENCE'):
            return 'UNKNOWN_REFERENCE'
        if error.startswith('TYPE_ERROR'):
            return 'TYPE_ERROR'
        if error.startswith('GROUND_INVALID') or error.startswith('INVENTORY'):
            return 'DSL_INVALID'
        return 'DSL_INVALID'
    if arm == 'b1' and ground_state is not None:
        state = ground_state
        if not state['needed'] <= set(state['extracted_atoms']):
            return 'GROUNDING_MISS'
        if not set(state['extracted_atoms']) <= state['gold_atoms']:
            return 'GROUNDING_WRONG_ATOM'
    if not valid or compiled is None:
        return 'REPRESENTATION_GAP'
    if arm in ('a0', 'b0'):
        pred_list = compiled  # already a flat program list
    else:
        pred_list = compiled[0] if compiled else None
    labels = _diff_label(pred_list,
                         list(case.admissible_program_sets[0]))
    return labels[0]


def phase_audit(root: Path, out: Path) -> int:
    stages = []
    if (out / f'{PREFIX_A}_results.json').exists():
        stages.append(('A', PREFIX_A, load_freeze_a,
                       ('a0', 'a1'), None))
    if (out / f'{PREFIX_B}_results.json').exists():
        stages.append(('B', PREFIX_B, load_freeze_b,
                       ('b0', 'b1'), 'ground'))
    audit = {'schema_version': 'guardian-vnext-grs-failure-audit-v1',
             'experiment': 'GRS_V1',
             'classification_basis': 'deterministic status/typed-field/triple diffs '
                                     'vs the gold program sets and gold inventories; '
                                     'no LLM judge; computed only after seal + score',
             'stages': {}}
    for stage, prefix, load_freeze, arms, extra_arm in stages:
        freeze, cases = load_freeze(root, out)
        results = json.loads((out / f'{prefix}_results.json').read_text(encoding='utf-8'))
        rows_by_arm = {arm: _load_sealed(out, prefix, arm, freeze,
                                         [c.case_id for c in cases]) for arm in arms}
        ground_rows = None
        ground_state = None
        if extra_arm:
            ground_rows = _load_sealed(out, prefix, extra_arm, freeze,
                                       [c.case_id for c in cases])
        stage_audit = {'results_verdict': results['verdict'],
                       'results_sha256': file_digest(out / f'{prefix}_results.json'),
                       'arms': {}}
        for arm in arms:
            classes, errors = {}, []
            for case in cases:
                row = rows_by_arm[arm][case.case_id]
                if arm in ('a0', 'b0'):
                    programs, valid = _h0_programs(row)
                    compiled, valid_flag = programs, valid
                    per_state = None
                else:
                    if ground_rows is not None:
                        grow = ground_rows[case.case_id]
                        inventory = None
                        if grow['status'].startswith('ok'):
                            inventory = _postvalidate_ground(grow['prediction'],
                                                             case.policy,
                                                             case.atom_catalog)
                        per_state = {'inventory': inventory,
                                     'extracted_atoms': sorted(
                                         {f['atom'] for f in inventory['facts']})
                                     if inventory else [],
                                     'needed': _gold_needed_atoms(case),
                                     'gold_atoms': _gold_inventory_atoms(case)}
                        alternatives, dropped, valid_flag = _grs_alternatives(
                            row, inventory) if inventory is not None else (None, [], False)
                    else:
                        alternatives, dropped, valid_flag = _grs_alternatives(
                            row, case.oracle_inventory)
                        per_state = None
                    compiled = alternatives
                if arm in ('a0', 'b0'):
                    correct, _per = _score_case(case, compiled, False)
                else:
                    correct, _per = _score_case(case, compiled, True)
                if correct:
                    continue
                classification = _classify_arm_case(case, row, arm, compiled,
                                                    valid_flag, per_state)
                classes[classification] = classes.get(classification, 0) + 1
                errors.append({'case_id': case.case_id, 'cohort': case.cohort,
                               'status': row['status'], 'error': row.get('error'),
                               'classification': classification,
                               'h0_representable': case.h0_representable,
                               'axes': list(case.axes), 'policy': case.policy})
            stage_audit['arms'][arm] = {'classes': classes,
                                        'error_count': len(errors),
                                        'errors': errors}
        audit['stages'][stage] = stage_audit
    audit_path = out / 'policy_grs_v1_failure_audit.json'
    if audit_path.exists():
        existing = json.loads(audit_path.read_text(encoding='utf-8'))
        if digest(existing) != digest(audit):
            raise ValueError('failure audit changed on recompute')
    else:
        write_new(audit_path, audit)
    print(json.dumps({'status': 'AUDIT_DONE',
                      'classes': {stage: {arm: audit['stages'][stage]['arms'][arm]['classes']
                                          for arm in audit['stages'][stage]['arms']}
                                  for stage in audit['stages']}}), flush=True)
    return 0


# ----------------------------------------------------------------------- main

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['freeze-a', 'smoke-a', 'run-a0', 'run-a1',
                                          'score-a', 'freeze-b', 'smoke-b', 'run-b0',
                                          'run-b1', 'score-b', 'audit'])
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env')
    parser.add_argument('--minutes', type=float, default=7.8)
    parser.add_argument('--repo-root', type=Path, default=ROOT)
    parser.add_argument('--out-dir', type=Path, default=ROOT / 'outputs/vnext')
    args = parser.parse_args()
    root, out = args.repo_root, args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    if args.phase == 'freeze-a':
        return phase_freeze_a(root, out)
    if args.phase == 'smoke-a':
        return phase_smoke_a(args.env_file, root, out)
    if args.phase == 'run-a0':
        return phase_run_a0(args.env_file, root, out, args.minutes)
    if args.phase == 'run-a1':
        return phase_run_a1(args.env_file, root, out, args.minutes)
    if args.phase == 'score-a':
        return phase_score_a(root, out)
    if args.phase == 'freeze-b':
        return phase_freeze_b(root, out)
    if args.phase == 'smoke-b':
        return phase_smoke_b(args.env_file, root, out)
    if args.phase == 'run-b0':
        return phase_run_b0(args.env_file, root, out, args.minutes)
    if args.phase == 'run-b1':
        return phase_run_b1(args.env_file, root, out, args.minutes)
    if args.phase == 'score-b':
        return phase_score_b(root, out)
    return phase_audit(root, out)


if __name__ == '__main__':
    raise SystemExit(main())
