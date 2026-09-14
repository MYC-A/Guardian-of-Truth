"""PSB causal experiment: frozen H0 vs H1 (structural binding) vs H2
(structural binding + conservative permission gate).

Preregistration: docs/vnext/PSB_PREREG_GATES_V1.json (frozen before the
first causal inference request). Phases:

  freeze   commit-clean check + corpus/gold/prereg freeze + H0 identity
           continuity vs the sealed PHV1 freeze + PSB identity freeze (no
           API calls)
  smoke    TWO synthetic non-benchmark requests (one H0 schema, one PSB
           schema) before the first semantic request
  run-h0   frozen H0 parse per case (byte-identical prompts/schema/config;
           one machine-validation-triggered repair re-ask), persisted,
           sealed before gold join
  run-psb  ONE PSB graph parse per case (same model/config; one repair
           re-ask), persisted, sealed before gold join; H1 and H2 are two
           deterministic compilations of this single sealed parse
  score    seals verified, then deterministic gold join + behavioral case
           correctness per arm + binding attachment metrics + permission
           metrics + regressions + correction precision + exact McNemar +
           frozen gate evaluation + causal verdict
  audit    deterministic post-seal failure taxonomy (no LLM judge)

Models never see gold: inputs are policy text and atom_catalog only.
Never start concurrently with another API job.
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
from guardian_truth.vnext import policy_psb as psb
from guardian_truth.vnext import policy_psb_causal_benchmark as corpus

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evaluate_vnext_c_alr_reimpl import (PARSE_TASK, REPAIR_TASK,  # noqa: E402
                                         STRUCTURE_SCHEMA, CONFIG,
                                         mcnemar_exact_p, newcombe_paired_ci)

ROOT = Path(__file__).resolve().parents[1]
PREFIX = 'policy_psb_causal_v1'
PREREG_DOC = 'docs/vnext/PSB_PREREG_GATES_V1.json'
PHV1_FREEZE_PATH = 'outputs/vnext/policy_phv1_holdout_v1_freeze.json'

SOURCES = [
    'src/guardian_truth/vnext/policy_psb.py',
    'src/guardian_truth/vnext/policy_psb_causal_benchmark.py',
    'src/guardian_truth/vnext/policy_v3_benchmark.py',
    'scripts/evaluate_vnext_c_alr_reimpl.py',
    'scripts/evaluate_vnext_policy_psb.py',
]

# Frozen causal gate values (must equal the preregistration 'causal_gates').
PSB_GATES = {
    "H1": {"binding_aggregate_micro_f1_gte": 0.85,
           "behavioral_h1_minus_h0_gte_pp": 0.10,
           "h0_correct_regression_rate_lte": 0.05},
    "H2": {"invented_permission_case_rate_lte": 0.02,
           "permission_clause_precision_gte": 0.95,
           "behavioral_h2_gte_behavioral_h1": True},
    "primary_candidate": {"behavioral_h2_minus_h0_gte_pp": 0.15},
    "validity_floor": {"schema_compile_validity_gte": 0.90},
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
    'behavioral_evaluator': 'psb.composed_verdict over compiled program sets '
                            '(v3.evaluate_v3_program per clause)',
    'case_correct_definition': 'the arm\'s compiled program set composes a '
                               'verdict on EVERY frozen world that belongs to '
                               'the acceptable set (composed verdicts of the '
                               'admissible gold program sets)',
}

PSB_IDENTITY = {
    'psb_parse_task_sha256': digest(psb.PSB_PARSE_TASK),
    'psb_repair_task_sha256': digest(psb.PSB_REPAIR_TASK),
    'psb_schema_sha256': digest(psb.PSB_SCHEMA),
    'compiler': 'psb.compile_psb_graph (deterministic; gate off for H1, on '
                'for H2 from the same sealed parse)',
    'permission_evidence': 'psb.positive_permission_evidence (frozen marker '
                           'classes; text-level; class-based, not '
                           'benchmark-specific strings)',
    'representation': 'typed attachment graph: nodes REGULATED/MODALITY/'
                      'CONDITION/EXCEPTION/ACTOR/QUALIFIER; edges REGULATES/'
                      'ACTIVATES/EXEMPTS/ACTOR_OF/QUALIFIES/SOURCE_OF/'
                      'PRECEDES/FOLLOWS; polarity via literal "!" prefix',
}

SMOKE_POLICY_H0 = 'You may open the paint store only during daylight hours.'
SMOKE_CATALOG_H0 = ['action:open_paint_store', 'distractor:smoke_case']
SMOKE_POLICY_PSB = 'The crane cab may be entered only after the banksman has signalled.'
SMOKE_CATALOG_PSB = ['action:enter_crane_cab', 'event:banksman_signalled',
                     'actor:assistant', 'distractor:smoke_case']

_REPAIR_TASK = {'h0': REPAIR_TASK, 'psb': psb.PSB_REPAIR_TASK}


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
             'atom_catalog': list(case.atom_catalog)} for case in cases]


def phase_freeze(root: Path, out: Path) -> int:
    freeze_path = out / f'{PREFIX}_freeze.json'
    bench_path = out / f'{PREFIX}_benchmark.json'
    if freeze_path.exists():
        raise FileExistsError('freeze already exists')
    prereg = json.loads((root / PREREG_DOC).read_text(encoding='utf-8'))
    if prereg['causal_gates'] != PSB_GATES:
        raise ValueError('runner gates differ from the preregistered gates')
    if prereg['causal_benchmark']['composition'] != corpus.COHORT_PLAN:
        raise ValueError('preregistered corpus composition mismatch')
    if prereg['causal_benchmark']['size'] != 44:
        raise ValueError('preregistered corpus size mismatch')
    # H0 identity continuity vs the sealed PHV1 freeze (machine check).
    phv1_path = root / PHV1_FREEZE_PATH
    phv1 = json.loads(phv1_path.read_text(encoding='utf-8'))
    continuity = {
        'phv1_freeze_path': PHV1_FREEZE_PATH,
        'phv1_freeze_sha256': file_digest(phv1_path),
        'phv1_architecture_commit': phv1['architecture_commit'],
        'parse_task_match': digest(PARSE_TASK) == phv1['h0_identity']['parse_task_sha256'],
        'repair_task_match': digest(REPAIR_TASK) == phv1['h0_identity']['repair_task_sha256'],
        'structure_schema_match': digest(STRUCTURE_SCHEMA) == phv1['h0_identity']['structure_schema_sha256'],
        'definition_match': digest(CONFIG) == phv1['h0_identity']['definition_sha256'],
    }
    for key in ('parse_task_match', 'repair_task_match', 'structure_schema_match',
                'definition_match'):
        if not continuity[key]:
            raise ValueError(f'H0 identity drift: {key} failed - H0 may not change')
    cases = corpus.build_psb_causal_benchmark()
    document = corpus.benchmark_psb_causal_document(cases)
    if subprocess.run(['git', 'diff', '--quiet', 'HEAD', '--', *SOURCES], cwd=root).returncode:
        raise ValueError('commit study implementation before freeze')
    for name in SOURCES:
        if subprocess.run(['git', 'ls-files', '--error-unmatch', name], cwd=root,
                          capture_output=True).returncode:
            raise ValueError('all frozen study sources must be tracked')
    commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root, capture_output=True,
                            text=True, check=True).stdout.strip()
    write_new(bench_path, document)
    write_new(freeze_path, {'schema_version': 'guardian-vnext-psb-freeze-v1',
                            'study': 'PSB_CAUSAL_V1',
                            'prereg': PREREG_DOC,
                            'architecture_commit': commit,
                            'h0_identity': H0_IDENTITY,
                            'h0_continuity': continuity,
                            'psb_identity': PSB_IDENTITY,
                            'definition': CONFIG, 'definition_sha256': digest(CONFIG),
                            'gates': PSB_GATES,
                            'prereg_sha256': file_digest(root / PREREG_DOC),
                            'case_ids': [case.case_id for case in cases],
                            'case_input_sha256': digest(_case_inputs(cases)),
                            'benchmark_sha256': file_digest(bench_path),
                            'gold_graph_sha256': digest(
                                {case.case_id: case.gold_graph for case in cases}),
                            'gold_frozen_before_predictions': True,
                            'gold_joined': False,
                            'source_sha256': {name: file_digest(root / name) for name in SOURCES},
                            'prompt_hash_policy': 'exact payload/messages/schema persisted '
                                                  'before every physical request',
                            'frozen_utc': datetime.now(timezone.utc).isoformat()})
    print(json.dumps({'status': 'FROZEN_NOT_RUN', 'cases': len(cases),
                      'commit': commit[:8], 'h0_continuity': 'VERIFIED',
                      'h0_representable': sum(c.h0_representable for c in cases)}))
    return 0


def load_freeze(root: Path, out: Path):
    freeze = json.loads((out / f'{PREFIX}_freeze.json').read_text(encoding='utf-8'))
    bench = json.loads((out / f'{PREFIX}_benchmark.json').read_text(encoding='utf-8'))
    if freeze['definition_sha256'] != digest(CONFIG) or freeze['gates'] != PSB_GATES \
            or freeze['h0_identity'] != H0_IDENTITY or freeze['psb_identity'] != PSB_IDENTITY:
        raise ValueError('frozen study configuration mismatch')
    if freeze['benchmark_sha256'] != file_digest(out / f'{PREFIX}_benchmark.json'):
        raise ValueError('benchmark storage hash mismatch')
    if freeze['prereg_sha256'] != file_digest(root / PREREG_DOC):
        raise ValueError('preregistration edited after freeze')
    cases = []
    for row in bench['cases']:
        case = corpus.PolicyPSBCase(
            case_id=row['case_id'], cohort=row['cohort'], family=row['family'],
            style=row['style'], policy=row['policy'],
            atom_catalog=tuple(row['atom_catalog']),
            gold_graph=row['gold_graph'],
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
    if freeze['gold_graph_sha256'] != digest(
            {case.case_id: case.gold_graph for case in cases}):
        raise ValueError('gold graphs changed after freeze')
    failures = verify_files(root, freeze['source_sha256'])
    if failures:
        raise ValueError(f'frozen source mismatch: {failures}')
    return freeze, cases


# ---------------------------------------------------------------------- smoke

def _make_delegate():
    config = provider_config(ClientConfig(timeout_seconds=180, max_output_tokens=2048,
                                          max_retries=0, response_format_mode='none'),
                             'bai', model='qwen3.8-flash')
    live: list = []
    delegate = DiagnosticSemanticBackend(ChatClient(config), interval_seconds=10,
                                        checkpoint=live.append)
    return delegate, live


def phase_smoke(env_file, root: Path, out: Path) -> int:
    freeze, _ = load_freeze(root, out)
    smoke_path = out / f'{PREFIX}_smoke.json'
    if smoke_path.exists():
        print(json.dumps({'status': 'SMOKE_ALREADY_DONE'}))
        return 0
    load_env_file(env_file)
    delegate, live = _make_delegate()
    stem = f'{PREFIX}_smoke'
    backend = PersistedSemanticBackend(delegate, out, stem,
                                       configuration_sha256=digest(freeze),
                                       live_records=live)
    h0 = backend.propose(PARSE_TASK,
                         {'policy_text': SMOKE_POLICY_H0,
                          'atom_catalog': SMOKE_CATALOG_H0},
                         STRUCTURE_SCHEMA)
    psb_prop = backend.propose(psb.PSB_PARSE_TASK,
                               {'policy_text': SMOKE_POLICY_PSB,
                                'atom_catalog': SMOKE_CATALOG_PSB},
                               psb.PSB_SCHEMA)
    smoke = {'schema_version': 'guardian-vnext-psb-smoke-v1',
             'purpose': 'synthetic non-benchmark schema/provider smoke BEFORE '
                        'the first semantic request (one H0 schema request, '
                        'one PSB schema request)',
             'payloads_are_benchmark_cases': False,
             'scored': False,
             'h0': {'transport_status': h0.transport_status,
                    'schema_status': h0.schema_status,
                    'error_category': h0.error_category},
             'psb': {'transport_status': psb_prop.transport_status,
                     'schema_status': psb_prop.schema_status,
                     'error_category': psb_prop.error_category},
             'telemetry': [dict(record) for record in backend.records]}
    write_new(smoke_path, smoke)
    if h0.transport_status != 'SUCCESS' or psb_prop.transport_status != 'SUCCESS':
        print(json.dumps({'status': 'SMOKE_TRANSPORT_FAILED'}))
        return 2
    print(json.dumps({'status': 'SMOKE_OK',
                      'h0_schema': h0.schema_status,
                      'psb_schema': psb_prop.schema_status}))
    return 0


# ------------------------------------------------------------------- run arms

def _run_parse_case(delegate, out: Path, freeze: dict, index: int, case, live: list,
                    arm: str, task: str, schema: dict, compile_value):
    """One case for one arm: primary parse + at most one frozen repair
    re-ask. Deterministic order, persisted per request. Returns the row."""
    stem = f'{PREFIX}_{arm}_{index:03d}'
    backend = PersistedSemanticBackend(delegate, out, stem,
                                        configuration_sha256=digest(freeze),
                                        live_records=live)
    payload = {'policy_text': case.policy, 'atom_catalog': list(case.atom_catalog)}
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
        repair = backend.propose(_REPAIR_TASK[arm], repair_payload, schema)
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


def _h0_compile(value):
    v3.compile_v3_structure(value)


def _psb_compile(value):
    psb.compile_psb_graph(value, permission_gate=False)


def _phase_run_arm(env_file, root: Path, out: Path, minutes: float, arm: str) -> int:
    freeze, cases = load_freeze(root, out)
    if not (out / f'{PREFIX}_smoke.json').exists():
        print(json.dumps({'status': 'NO_SMOKE', 'note': 'run the smoke phase first'}))
        return 2
    rows_path = out / f'{PREFIX}_{arm}_predictions.json'
    if rows_path.exists():
        print(json.dumps({'status': 'ALREADY_SEALED', 'arm': arm}))
        return 0
    if arm == 'h0':
        task, schema, compile_value = PARSE_TASK, STRUCTURE_SCHEMA, _h0_compile
    else:
        task, schema, compile_value = psb.PSB_PARSE_TASK, psb.PSB_SCHEMA, _psb_compile
    load_env_file(env_file)
    delegate, live = _make_delegate()
    started = time.monotonic()
    rows = []
    for index, case in enumerate(cases):
        row_path = out / f'{PREFIX}_{arm}_case_{index:03d}.json'
        if row_path.exists():
            row = json.loads(row_path.read_text(encoding='utf-8'))
            if row['case_id'] != case.case_id or row['configuration_sha256'] != digest(freeze):
                raise ValueError(f'cached {arm} case changed')
        else:
            try:
                row = _run_parse_case(delegate, out, freeze, index, case, live,
                                      arm, task, schema, compile_value)
            except ProviderPause as error:
                print(json.dumps({'status': 'PROVIDER_PAUSED', 'reason': str(error),
                                  'arm': arm, 'completed': len(rows),
                                  'total': len(cases)}), flush=True)
                return 2
            write_new(row_path, row)
        rows.append(row)
        # Transport/schema facts only: no semantic inspection during inference.
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
    write_new(out / f'{PREFIX}_{arm}_prediction_seal.json', seal)
    print(json.dumps({'status': 'SEALED', 'arm': arm, 'cases': len(rows),
                      'ok': sum(row['status'].startswith('ok') for row in rows)}),
          flush=True)
    return 0


def phase_run_h0(env_file, root: Path, out: Path, minutes: float) -> int:
    return _phase_run_arm(env_file, root, out, minutes, 'h0')


def phase_run_psb(env_file, root: Path, out: Path, minutes: float) -> int:
    return _phase_run_arm(env_file, root, out, minutes, 'psb')


# ---------------------------------------------------------------------- score

def _arm_programs(case, row, arm):
    """Compile a sealed prediction row into the arm's program set.
    Returns (programs, valid_flag). H0: one flat program (None when invalid).
    H1: graph compiled gate-off. H2: graph compiled gate-on (rejected
    permission clauses recorded)."""
    prediction = row['prediction']
    if prediction is None:
        return None, False
    try:
        if arm == 'h0':
            program = v3.compile_v3_structure(dict(prediction))
            return [program], True
        programs, _rejected = psb.compile_psb_graph(
            dict(prediction), permission_gate=(arm == 'h2'),
            policy_text=case.policy)
        return programs, True
    except (v3.StructureInvalid, psb.PSBInvalid, ValueError, TypeError):
        return None, False


def _permission_clauses(programs):
    out = set()
    for program in programs or []:
        if program['modality'] == 'PERMISSION':
            for clause in program['target_clauses']:
                out.add(frozenset(clause))
    return out


def _gold_permission_clauses(case):
    out = set()
    for admissible in case.admissible_program_sets:
        out |= _permission_clauses(list(admissible))
    return out


def _invented_permission(per_world):
    for world in per_world or []:
        if world.get('verdict') == 'PERMITTED' \
                and 'PERMITTED' not in world.get('acceptable', []):
            return True
    return False


def _paired(a_results, b_results, cases):
    """Discordant counts for a vs b (a = candidate, b = baseline)."""
    corrections = sum(1 for case in cases
                      if not b_results[case.case_id] and a_results[case.case_id])
    regressions = sum(1 for case in cases
                      if b_results[case.case_id] and not a_results[case.case_id])
    return corrections, regressions


def _correction_precision(corrections, regressions):
    total = corrections + regressions
    return (corrections / total) if total else None


def phase_score(root: Path, out: Path) -> int:
    freeze, cases = load_freeze(root, out)
    n = len(cases)
    rows_by_arm = {}
    for arm in ('h0', 'psb'):
        rows_path = out / f'{PREFIX}_{arm}_predictions.json'
        rows = json.loads(rows_path.read_text(encoding='utf-8'))
        seal = json.loads((out / f'{PREFIX}_{arm}_prediction_seal.json').read_text(encoding='utf-8'))
        expected = prediction_seal(rows, [case.case_id for case in cases],
                                   architecture_commit=freeze['architecture_commit'],
                                   configuration_sha256=digest(freeze))
        if seal != expected:
            raise ValueError(f'{arm} prediction seal invalid; gold was not opened before seal')
        rows_by_arm[arm] = {row['case_id']: row for row in rows}

    arms = {'h0': {}, 'h1': {}, 'h2': {}}
    per_case = {'h0': {}, 'h1': {}, 'h2': {}}
    rejected_permissions = {}
    for arm in ('h0', 'h1', 'h2'):
        for case in cases:
            row = (rows_by_arm['h0'] if arm == 'h0' else rows_by_arm['psb'])[case.case_id]
            programs, valid = _arm_programs(case, row, arm)
            if arm == 'h2':
                try:
                    _, rejected = psb.compile_psb_graph(
                        dict(row['prediction']), permission_gate=True,
                        policy_text=case.policy)
                    rejected_permissions[case.case_id] = rejected
                except (psb.PSBInvalid, ValueError, TypeError):
                    rejected_permissions[case.case_id] = None
            if programs is None:
                correct, per_world = False, None
            else:
                correct, per_world = psb.score_program_set(
                    programs, case.worlds, case.admissible_program_sets)
            arms[arm][case.case_id] = {'programs': programs, 'valid': valid,
                                       'status': row['status']}
            per_case[arm][case.case_id] = {'correct': correct, 'per_world': per_world,
                                           'status': row['status']}

    def accuracy(arm, subset=None):
        members = [case for case in cases if subset is None or subset(case)]
        k = sum(per_case[arm][case.case_id]['correct'] for case in members)
        return {'n': len(members), 'correct': k,
                'accuracy': round(k / len(members), 4) if members else None}

    behavioral = {arm: accuracy(arm) for arm in arms}
    validity = {arm: sum(1 for case in cases if arms[arm][case.case_id]['valid']) / n
                for arm in arms}
    cohort_metrics = {}
    for arm in arms:
        cohort_metrics[arm] = {}
        for cohort in sorted({case.cohort for case in cases}):
            cohort_metrics[arm][cohort] = accuracy(
                arm, lambda c, co=cohort: c.cohort == co)
    representable_metrics = {
        arm: accuracy(arm, lambda c: c.h0_representable) for arm in arms}
    capacity_metrics = {
        arm: accuracy(arm, lambda c: not c.h0_representable) for arm in arms}
    family_metrics = {}
    for arm in arms:
        families = {}
        for case in cases:
            families.setdefault(case.family, [0, 0])
            families[case.family][0] += 1
            families[case.family][1] += per_case[arm][case.case_id]['correct']
        family_metrics[arm] = {family: {'n': counts[0], 'correct': counts[1],
                                        'accuracy': round(counts[1] / counts[0], 4)}
                               for family, counts in sorted(families.items())}

    # binding attachment metrics (H0: flat projection; PSB arm: graph triples)
    gold_triples = {case.case_id: psb.canonical_triples_graph(case.gold_graph)
                    for case in cases}
    h0_triples = {}
    for case in cases:
        programs = arms['h0'][case.case_id]['programs']
        h0_triples[case.case_id] = (psb.canonical_triples_flat(programs[0])
                                    if programs else set())
    psb_triples = {}
    for case in cases:
        prediction = rows_by_arm['psb'][case.case_id]['prediction']
        psb_triples[case.case_id] = (psb.canonical_triples_graph(prediction)
                                     if prediction is not None else set())
    binding = {'h0_flat_projection': psb.binding_metrics(h0_triples, gold_triples),
               'psb_graph': psb.binding_metrics(psb_triples, gold_triples)}

    # permission metrics
    permission = {}
    for arm in arms:
        predicted_all, matched_pred, gold_all, matched_gold = [], 0, [], 0
        invented_cases, missed_cases = 0, 0
        for case in cases:
            programs = arms[arm][case.case_id]['programs'] or []
            predicted = _permission_clauses(programs)
            gold = _gold_permission_clauses(case)
            predicted_all.extend(predicted)
            matched_pred += len(predicted & gold)
            gold_all.extend(gold)
            matched_gold += len(predicted & gold)
            if _invented_permission(per_case[arm][case.case_id]['per_world']):
                invented_cases += 1
            if gold and not (predicted & gold):
                missed_cases += 1
        permission[arm] = {
            'permission_clause_precision': round(matched_pred / len(predicted_all), 4)
            if predicted_all else None,
            'permission_clause_recall': round(matched_gold / len(gold_all), 4)
            if gold_all else None,
            'invented_permission_cases': invented_cases,
            'invented_permission_case_rate': round(invented_cases / n, 4),
            'missed_explicit_permission_cases': missed_cases,
            'missed_explicit_permission_rate': round(missed_cases / n, 4),
            'n_predicted_permission_clauses': len(predicted_all),
            'n_gold_permission_clauses': len(gold_all)}

    # paired statistics
    pairs = {}
    for name, cand, base in (('h1_vs_h0', 'h1', 'h0'), ('h2_vs_h1', 'h2', 'h1'),
                             ('h2_vs_h0', 'h2', 'h0')):
        corrections, regressions = _paired(per_case[cand], per_case[base], cases)
        delta = behavioral[cand]['accuracy'] - behavioral[base]['accuracy']
        ci = newcombe_paired_ci(corrections, regressions, n)
        pairs[name] = {'corrections': corrections, 'regressions': regressions,
                       'delta_accuracy': round(delta, 4),
                       'newcombe_paired_ci95_delta': [round(ci[0], 4), round(ci[1], 4)],
                       'mcnemar_exact_p_two_sided': round(
                           mcnemar_exact_p(corrections, regressions), 6),
                       'correction_precision': _correction_precision(corrections, regressions)}
    h0_correct = [case for case in cases if per_case['h0'][case.case_id]['correct']]
    regressions = {}
    for arm in ('h1', 'h2'):
        wrong = sum(1 for case in h0_correct if not per_case[arm][case.case_id]['correct'])
        regressions[f'h0_correct_to_{arm}_wrong'] = {
            'n_h0_correct': len(h0_correct), 'wrong': wrong,
            'rate': round(wrong / len(h0_correct), 4) if h0_correct else None}

    # gate evaluation (frozen)
    h0_acc = behavioral['h0']['accuracy']
    h1_acc = behavioral['h1']['accuracy']
    h2_acc = behavioral['h2']['accuracy']
    binding_f1 = binding['psb_graph']['aggregate']['f1']
    gates = PSB_GATES
    h1_gates = {
        'binding_aggregate_micro_f1': binding_f1,
        'binding_pass': binding_f1 is not None
        and binding_f1 >= gates['H1']['binding_aggregate_micro_f1_gte'],
        'behavioral_delta': round(h1_acc - h0_acc, 4),
        'behavioral_pass': h1_acc - h0_acc >= gates['H1']['behavioral_h1_minus_h0_gte_pp'],
        'regression_rate': regressions['h0_correct_to_h1_wrong']['rate'],
        'regression_pass': regressions['h0_correct_to_h1_wrong']['rate'] is not None
        and regressions['h0_correct_to_h1_wrong']['rate']
        <= gates['H1']['h0_correct_regression_rate_lte']}
    h1_supported = (h1_gates['binding_pass'] and h1_gates['behavioral_pass']
                    and h1_gates['regression_pass'])
    h2_gates = {
        'invented_permission_case_rate': permission['h2']['invented_permission_case_rate'],
        'invented_permission_pass': permission['h2']['invented_permission_case_rate']
        <= gates['H2']['invented_permission_case_rate_lte'],
        'permission_clause_precision': permission['h2']['permission_clause_precision'],
        'precision_pass': permission['h2']['permission_clause_precision'] is not None
        and permission['h2']['permission_clause_precision']
        >= gates['H2']['permission_clause_precision_gte'],
        'behavioral_h2': h2_acc, 'behavioral_h1': h1_acc,
        'behavioral_pass': h2_acc >= h1_acc}
    h2_supported = (h2_gates['invented_permission_pass'] and h2_gates['precision_pass']
                    and h2_gates['behavioral_pass'])
    primary = {'behavioral_h2_minus_h0': round(h2_acc - h0_acc, 4),
               'pass': h2_acc - h0_acc >= gates['primary_candidate']['behavioral_h2_minus_h0_gte_pp']}
    validity_floor_pass = all(validity[arm] >= gates['validity_floor']['schema_compile_validity_gte']
                              for arm in arms)
    if not validity_floor_pass:
        verdict = 'INFRASTRUCTURE_FAILURE'
    elif h1_supported and h2_supported and primary['pass']:
        verdict = 'PROMOTE_TO_NEW_HOLDOUT'
    elif not h1_supported and not h2_supported:
        verdict = 'REJECT_BOTH'
    elif not h1_supported:
        verdict = 'REJECT_STRUCTURAL_BINDING_HYPOTHESIS'
    elif not h2_supported:
        verdict = 'REJECT_PERMISSION_GATE_HYPOTHESIS'
    else:
        verdict = 'HYPOTHESES_SUPPORTED_CANDIDATE_NOT_PROMOTED'

    tokens, latencies, requests = {}, {}, {}
    for arm in ('h0', 'psb'):
        arm_tokens, arm_lat = 0, []
        for index in range(n):
            row_path = out / f'{PREFIX}_{arm}_case_{index:03d}.json'
            row = json.loads(row_path.read_text(encoding='utf-8')) if row_path.exists() else {}
            for record in row.get('request_records', []):
                arm_tokens += record.get('usage', {}).get('total_tokens', 0)
                if record.get('latency_ms'):
                    arm_lat.append(float(record['latency_ms']))
        tokens[arm] = arm_tokens
        latencies[arm] = arm_lat
    efficiency = {arm: {'requests': len(latencies[arm]), 'total_tokens': tokens[arm],
                        'median_latency_ms': percentile(latencies[arm], .5)
                        if latencies[arm] else None,
                        'p95_latency_ms': percentile(latencies[arm], .95)
                        if latencies[arm] else None}
                  for arm in ('h0', 'psb')}

    report = {'schema_version': 'guardian-vnext-psb-results-v1',
              'experiment': 'PSB_CAUSAL_V1',
              'prereg': PREREG_DOC,
              'architecture_commit': freeze['architecture_commit'],
              'freeze_sha256': file_digest(out / f'{PREFIX}_freeze.json'),
              'benchmark_sha256': freeze['benchmark_sha256'],
              'case_count': n,
              'arms': {'h0': 'frozen flat single-structure (byte-identical to PHV1 H0)',
                       'h1': 'typed attachment graph + deterministic compilation',
                       'h2': 'h1 + frozen positive-evidence permission gate (same sealed parse)'},
              'primary_metric': {arm: {'correct': behavioral[arm]['correct'],
                                       'n': n,
                                       'accuracy': behavioral[arm]['accuracy'],
                                       'wilson_ci95': [round(v, 4) for v in
                                                       wilson_ci(behavioral[arm]['correct'], n)]}
                                 for arm in arms},
              'validity': {arm: round(validity[arm], 4) for arm in arms},
              'cohorts': cohort_metrics,
              'families': family_metrics,
              'h0_representable_subset': representable_metrics,
              'capacity_subset': capacity_metrics,
              'binding_attachment': binding,
              'permission': permission,
              'rejected_permission_clauses_h2': {cid: rejected for cid, rejected
                                                 in rejected_permissions.items() if rejected},
              'paired_statistics': pairs,
              'regressions': regressions,
              'gates_evaluation': {'H1': h1_gates, 'H2': h2_gates,
                                   'primary_candidate': primary,
                                   'validity_floor_pass': validity_floor_pass,
                                   'gates': gates},
              'h1_hypothesis_supported': h1_supported,
              'h2_hypothesis_supported': h2_supported,
              'verdict': verdict,
              'research_questions': {
                  'Q1_relation_binding_dominant_cause': 'see binding_attachment.h0_flat_projection '
                                                        'vs psb_graph and failure audit',
                  'Q2_explicit_structure_improves_behavior': h1_gates['behavioral_pass'],
                  'Q3_condition_exception_attachment_errors_reduced':
                      round((binding['h0_flat_projection']['per_class']['EXCEPTION']['f1'] or 0)
                            if binding['h0_flat_projection']['per_class']['EXCEPTION']['f1'] is not None else 0, 4),
                  'Q4_multiaxis_improved': round(
                      cohort_metrics['h1']['multiaxis_controls']['accuracy']
                      - cohort_metrics['h0']['multiaxis_controls']['accuracy'], 4),
                  'Q5_gate_removes_invented_permission': {
                      'h0': permission['h0']['invented_permission_case_rate'],
                      'h1': permission['h1']['invented_permission_case_rate'],
                      'h2': permission['h2']['invented_permission_case_rate']},
                  'Q6_correction_precision_structural': pairs['h1_vs_h0']['correction_precision'],
                  'Q7_regressions_on_simple': regressions,
                  'Q8_generalizes_to_new_holdout': 'NOT TESTED (Stage B, conditional)',
                  'Q9_ready_for_integration': 'NOT TESTED (decided by Stage B or by stop rule)'},
              'efficiency': efficiency,
              'historical_context': {
                  'h0_v5_recovered': '136/142 = 95.77% (machine-verified, controlled dev distribution)',
                  'phv1_prospective': '59/80 = 73.75% (machine-verified prospective holdout; '
                                      'development evidence for this cycle)',
                  'comparison_rule': 'separate implementations/distributions; never a '
                                     'unified learning curve'}}
    results_path = out / f'{PREFIX}_results.json'
    if results_path.exists():
        existing = json.loads(results_path.read_text(encoding='utf-8'))
        if digest(existing) != digest(report):
            raise ValueError('results report changed on recompute')
    else:
        write_new(results_path, report)
    print(json.dumps({'experiment': 'PSB_CAUSAL_V1',
                      'h0': behavioral['h0']['accuracy'],
                      'h1': behavioral['h1']['accuracy'],
                      'h2': behavioral['h2']['accuracy'],
                      'binding_f1': binding_f1,
                      'invented_perm': {'h0': permission['h0']['invented_permission_case_rate'],
                                        'h1': permission['h1']['invented_permission_case_rate'],
                                        'h2': permission['h2']['invented_permission_case_rate']},
                      'perm_precision_h2': permission['h2']['permission_clause_precision'],
                      'h1_supported': h1_supported, 'h2_supported': h2_supported,
                      'primary_pass': primary['pass'],
                      'verdict': verdict}), flush=True)
    return 0


# ---------------------------------------------------------------------- audit

def _axis_diffs_set(pred_programs, gold_programs):
    """Axis diffs between the closest single gold program and the predicted
    program set (deterministic: minimal diff count, then sorted labels)."""
    best, best_diffs = None, None
    for gold in gold_programs:
        diffs = []
        for pred in pred_programs:
            if pred['target_clauses'] == gold['target_clauses']:
                if pred['modality'] != gold['modality']:
                    diffs.append('modality_attachment')
                if pred['relation'] != gold['relation']:
                    diffs.append('relation_strength')
                pc, pe = set(pred['condition_literals']), set(pred['exception_literals'])
                gc, ge = set(gold['condition_literals']), set(gold['exception_literals'])
                if (pc | pe) != (gc | ge) or pc != gc:
                    if (pc | pe) == (gc | ge) and pe != ge:
                        diffs.append('condition_exception_confusion')
                    elif ({l[1:] if l.startswith('!') else l for l in pc} ==
                          {l[1:] if l.startswith('!') else l for l in gc}
                          and {l[1:] if l.startswith('!') else l for l in pe} ==
                          {l[1:] if l.startswith('!') else l for l in ge}):
                        diffs.append('polarity')
                    else:
                        pred_actors = {l for l in pc if l.startswith('actor:')}
                        gold_actors = {l for l in gc if l.startswith('actor:')}
                        if (pc - pred_actors) == (gc - gold_actors) \
                                and pred_actors != gold_actors:
                            diffs.append('actor_attachment')
                        else:
                            diffs.append('atom_recognition')
                if pred['temporal'] != gold['temporal']:
                    diffs.append('temporal')
        if not diffs and not any(pred['target_clauses'] == gold['target_clauses']
                                 for pred in pred_programs):
            diffs.append('atom_recognition')
        if best_diffs is None or (len(diffs), sorted(diffs)) < (len(best_diffs), sorted(best_diffs)):
            best, best_diffs = gold, diffs
    return best_diffs or []


def _classify(pred_programs, gold_programs, valid):
    if not valid or not pred_programs:
        return 'representation_gap'
    diffs = _axis_diffs_set(pred_programs, gold_programs)
    if not diffs:
        return 'other'
    if len(diffs) == 1:
        return diffs[0]
    return 'multi_axis'


def phase_audit(root: Path, out: Path) -> int:
    freeze, cases = load_freeze(root, out)
    results = json.loads((out / f'{PREFIX}_results.json').read_text(encoding='utf-8'))
    rows_by_arm = {arm: {row['case_id']: row for row in json.loads(
        (out / f'{PREFIX}_{arm}_predictions.json').read_text(encoding='utf-8'))}
        for arm in ('h0', 'psb')}
    audits = {}
    for arm in ('h0', 'h1', 'h2'):
        classes, errors = {}, []
        for case in cases:
            row = rows_by_arm['h0'] if arm == 'h0' else rows_by_arm['psb']
            programs, valid = _arm_programs(case, row[case.case_id], arm)
            correct = None
            if programs is not None:
                correct, _per = psb.score_program_set(
                    programs, case.worlds, case.admissible_program_sets)
            if correct:
                continue
            classification = _classify(programs, list(case.admissible_program_sets[0]), valid)
            classes[classification] = classes.get(classification, 0) + 1
            entry = {'case_id': case.case_id, 'cohort': case.cohort,
                     'family': case.family, 'status': row[case.case_id]['status'],
                     'classification': classification,
                     'h0_representable': case.h0_representable,
                     'axes': list(case.axes), 'policy': case.policy}
            if arm != 'h0' and row[case.case_id]['prediction'] is not None:
                pred_triples = psb.canonical_triples_graph(row[case.case_id]['prediction'])
                gold_triples = psb.canonical_triples_graph(case.gold_graph)
                entry['missing_gold_triples'] = sorted(
                    f"{t[0]}:{sorted(t[1])}->{sorted(t[2])}" for t in gold_triples - pred_triples)
                entry['invented_triples'] = sorted(
                    f"{t[0]}:{sorted(t[1])}->{sorted(t[2])}" for t in pred_triples - gold_triples)
            errors.append(entry)
        audits[arm] = {'classes': classes, 'error_count': len(errors), 'errors': errors}
    audit = {'schema_version': 'guardian-vnext-psb-failure-audit-v1',
             'experiment': 'PSB_CAUSAL_V1',
             'results_verdict': results['verdict'],
             'results_sha256': file_digest(out / f'{PREFIX}_results.json'),
             'classification_basis': 'deterministic typed-field and triple diffs vs the '
                                     'gold program set and gold graph; no LLM judge; '
                                     'computed only after seal + score',
             'arms': audits}
    audit_path = out / f'{PREFIX}_failure_audit.json'
    if audit_path.exists():
        existing = json.loads(audit_path.read_text(encoding='utf-8'))
        if digest(existing) != digest(audit):
            raise ValueError('failure audit changed on recompute')
    else:
        write_new(audit_path, audit)
    print(json.dumps({'status': 'AUDIT_DONE',
                      'classes': {arm: audits[arm]['classes'] for arm in audits}}),
          flush=True)
    return 0


# ----------------------------------------------------------------------- main

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['freeze', 'smoke', 'run-h0', 'run-psb',
                                          'score', 'audit'])
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env')
    parser.add_argument('--minutes', type=float, default=7.8)
    parser.add_argument('--repo-root', type=Path, default=ROOT)
    parser.add_argument('--out-dir', type=Path, default=ROOT / 'outputs/vnext')
    args = parser.parse_args()
    root, out = args.repo_root, args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    if args.phase == 'freeze':
        return phase_freeze(root, out)
    if args.phase == 'smoke':
        return phase_smoke(args.env_file, root, out)
    if args.phase == 'run-h0':
        return phase_run_h0(args.env_file, root, out, args.minutes)
    if args.phase == 'run-psb':
        return phase_run_psb(args.env_file, root, out, args.minutes)
    if args.phase == 'score':
        return phase_score(root, out)
    return phase_audit(root, out)


if __name__ == '__main__':
    raise SystemExit(main())
