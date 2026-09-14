"""PHV1 - Policy H0 Prospective Holdout V1 (docs/vnext/PHV1_PREREG_GATES_V1.json).

Prospective frozen holdout validation of the EXISTING conservative Policy
frontend H0 on 80 NEW unseen policy texts. VALIDATE, DO NOT IMPROVE: no new
architecture, no mutation catalog, no C-ALR verifier, no LLM judges.

H0 identity: PARSE_TASK, REPAIR_TASK, STRUCTURE_SCHEMA and CONFIG are imported
BYTE-IDENTICAL from scripts/evaluate_vnext_c_alr_reimpl.py (the study that
produced the machine-verified 136/142 on the recovered V5 benchmark), and the
freeze phase machine-verifies continuity against the sealed C-ALR freeze
(outputs/vnext/policy_c_alr_reimpl_v1_freeze.json). Any drift aborts.

Phases:
  freeze   commit-clean check + corpus/gold/prereg freeze + H0 identity
           continuity check (no API calls)
  smoke    ONE synthetic non-benchmark schema/provider request (transport +
           schema path check) before the first semantic request
  run-h0   one conservative parse per case (+ the frozen single
           machine-validation-triggered repair re-ask; max 2 requests per
           case), resumable per-case persisted requests, sealed before gold
           join. Prints ONLY transport/schema/status facts (no semantic
           inspection during inference).
  score    deterministic gold join + behavioral accuracy + Wilson CI + cohort
           and family metrics + structural secondary metrics (NOT_MEASURED
           policy) + unsupported-semantics counters + preregistered gates +
           verdict (PROMOTE_TO_INTEGRATION / REVISE / REOPEN_POLICY_RESEARCH)
  audit    deterministic post-seal residual classification (no LLM judge)

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
from guardian_truth.vnext import policy_phv1_holdout as phv1

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evaluate_vnext_c_alr_reimpl import PARSE_TASK, REPAIR_TASK, STRUCTURE_SCHEMA, CONFIG  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PREFIX = 'policy_phv1_holdout_v1'
PREREG_DOC = 'docs/vnext/PHV1_PREREG_GATES_V1.json'
C_ALR_FREEZE_PATH = 'outputs/vnext/policy_c_alr_reimpl_v1_freeze.json'

SOURCES = [
    'src/guardian_truth/vnext/policy_phv1_holdout.py',
    'src/guardian_truth/vnext/policy_v3_benchmark.py',
    'scripts/evaluate_vnext_c_alr_reimpl.py',
    'scripts/evaluate_vnext_policy_phv1.py',
]

# Frozen gate values (must equal docs/vnext/PHV1_PREREG_GATES_V1.json 'gates').
PHV1_GATES = {
    "primary": {"overall_behavioral_accuracy_gte": 0.90},
    "cohort": {"simple_gte": 0.95, "nl_stress_gte": 0.80, "structural_aggregate_gte": 0.85},
    "validity": {"schema_compile_validity_gte": 0.98},
    "safety": {"invented_explicit_permission_case_rate_lte": 0.02,
               "unsupported_restrictive_reading_case_rate_lte": 0.05},
    "family_floor": {"applies_to_families_with_n_at_least": 8, "behavioral_accuracy_gte": 0.60},
    "reopen": {"overall_below": 0.85, "major_family_collapses_gte": 2,
               "structural_aggregate_below": 0.70},
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
    'behavioral_evaluator': 'v3.evaluate_v3_program via v3.score_candidate_structure',
    'case_correct_definition': 'candidate compiled verdicts match SOME admissible '
                               'gold program verdicts on EVERY frozen world',
}

SMOKE_POLICY = 'You may open the paint store only during daylight hours.'
SMOKE_CATALOG = ['action:open_paint_store', 'distractor:smoke_case']


# ------------------------------------------------------------------ statistics

def wilson_ci(k: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion (two-sided 95%)."""
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
    prereg_path = root / PREREG_DOC
    prereg = json.loads(prereg_path.read_text(encoding='utf-8'))
    if prereg['gates'] != PHV1_GATES:
        raise ValueError('runner gates differ from the preregistered gates')
    if prereg['corpus']['size'] != 80 or prereg['corpus']['composition'] != phv1.COHORT_PLAN:
        raise ValueError('preregistered corpus composition mismatch')
    # H0 identity continuity vs the sealed C-ALR freeze (machine check).
    c_alr_path = root / C_ALR_FREEZE_PATH
    c_alr = json.loads(c_alr_path.read_text(encoding='utf-8'))
    continuity = {
        'c_alr_freeze_path': C_ALR_FREEZE_PATH,
        'c_alr_freeze_sha256': file_digest(c_alr_path),
        'c_alr_architecture_commit': c_alr['architecture_commit'],
        'parse_task_match': digest(PARSE_TASK) == c_alr['prompt_freeze']['parse_task_sha256'],
        'repair_task_match': digest(REPAIR_TASK) == c_alr['prompt_freeze']['repair_task_sha256'],
        'structure_schema_match': digest(STRUCTURE_SCHEMA) == c_alr['prompt_freeze']['structure_schema_sha256'],
        'definition_match': digest(CONFIG) == c_alr['definition_sha256'],
    }
    for key in ('parse_task_match', 'repair_task_match', 'structure_schema_match',
                'definition_match'):
        if not continuity[key]:
            raise ValueError(f'H0 identity drift: {key} failed - H0 may not change')
    cases = phv1.build_phv1_holdout()
    document = phv1.benchmark_phv1_document(cases)
    if subprocess.run(['git', 'diff', '--quiet', 'HEAD', '--', *SOURCES], cwd=root).returncode:
        raise ValueError('commit study implementation before freeze')
    for name in SOURCES:
        if subprocess.run(['git', 'ls-files', '--error-unmatch', name], cwd=root,
                          capture_output=True).returncode:
            raise ValueError('all frozen study sources must be tracked')
    commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root, capture_output=True,
                            text=True, check=True).stdout.strip()
    write_new(bench_path, document)
    write_new(freeze_path, {'schema_version': 'guardian-vnext-phv1-freeze-v1',
                            'study': 'PHV1',
                            'prereg': PREREG_DOC,
                            'architecture_commit': commit,
                            'h0_identity': H0_IDENTITY,
                            'h0_continuity': continuity,
                            'definition': CONFIG, 'definition_sha256': digest(CONFIG),
                            'gates': PHV1_GATES,
                            'prereg_sha256': file_digest(prereg_path),
                            'case_ids': [case.case_id for case in cases],
                            'case_input_sha256': digest(_case_inputs(cases)),
                            'benchmark_sha256': file_digest(bench_path),
                            'gold_frozen_before_predictions': True,
                            'gold_joined': False,
                            'source_sha256': {name: file_digest(root / name) for name in SOURCES},
                            'prompt_hash_policy': 'exact payload/messages/schema persisted '
                                                  'before every physical request',
                            'frozen_utc': datetime.now(timezone.utc).isoformat()})
    print(json.dumps({'status': 'FROZEN_NOT_RUN', 'cases': len(cases),
                      'commit': commit[:8], 'h0_continuity': 'VERIFIED'}))
    return 0


def load_freeze(root: Path, out: Path):
    freeze = json.loads((out / f'{PREFIX}_freeze.json').read_text(encoding='utf-8'))
    bench = json.loads((out / f'{PREFIX}_benchmark.json').read_text(encoding='utf-8'))
    if freeze['definition_sha256'] != digest(CONFIG) or freeze['gates'] != PHV1_GATES \
            or freeze['h0_identity'] != H0_IDENTITY:
        raise ValueError('frozen study configuration mismatch')
    if freeze['benchmark_sha256'] != file_digest(out / f'{PREFIX}_benchmark.json'):
        raise ValueError('benchmark storage hash mismatch')
    if freeze['prereg_sha256'] != file_digest(root / PREREG_DOC):
        raise ValueError('preregistration edited after freeze')
    cases = []
    for row in bench['cases']:
        case = phv1.PolicyPHV1Case(case_id=row['case_id'], cohort=row['cohort'],
                                   family=row['family'], style=row['style'],
                                   policy=row['policy'],
                                   atom_catalog=tuple(row['atom_catalog']),
                                   ambiguous=row['ambiguous'], trap=row['trap'],
                                   admissible_structures=tuple(dict(s) for s in row['admissible_structures']),
                                   admissible_programs=tuple(dict(p) for p in row['admissible_programs']),
                                   worlds=tuple(dict(w) for w in row['worlds']),
                                   axes=tuple(row.get('axes', ())))
        cases.append(case)
    if freeze['case_ids'] != [case.case_id for case in cases]:
        raise ValueError('frozen case identity mismatch')
    if freeze['case_input_sha256'] != digest(_case_inputs(cases)):
        raise ValueError('case inputs changed after freeze')
    failures = verify_files(root, freeze['source_sha256'])
    if failures:
        raise ValueError(f'frozen source mismatch: {failures}')
    return freeze, cases


# ---------------------------------------------------------------------- smoke

def phase_smoke(env_file, root: Path, out: Path) -> int:
    freeze, _ = load_freeze(root, out)
    smoke_path = out / f'{PREFIX}_smoke.json'
    if smoke_path.exists():
        print(json.dumps({'status': 'SMOKE_ALREADY_DONE'}))
        return 0
    load_env_file(env_file)
    config = provider_config(ClientConfig(timeout_seconds=180, max_output_tokens=2048,
                                          max_retries=0, response_format_mode='none'),
                             'bai', model='qwen3.8-flash')
    live: list = []
    delegate = DiagnosticSemanticBackend(ChatClient(config), interval_seconds=10,
                                        checkpoint=live.append)
    stem = f'{PREFIX}_smoke'
    backend = PersistedSemanticBackend(delegate, out, stem,
                                       configuration_sha256=digest(freeze),
                                       live_records=live)
    payload = {'policy_text': SMOKE_POLICY, 'atom_catalog': SMOKE_CATALOG}
    proposal = backend.propose(PARSE_TASK, payload, STRUCTURE_SCHEMA)
    record = dict(backend.records[-1])
    if record.get('usage'):
        record['usage'] = {k: record['usage'][k] for k in sorted(record['usage'])}
    smoke = {'schema_version': 'guardian-vnext-phv1-smoke-v1',
             'purpose': 'synthetic non-benchmark schema/provider smoke BEFORE the '
                        'first semantic request (prereg section 27)',
             'payload_is_benchmark_case': False,
             'scored': False,
             'transport_status': proposal.transport_status,
             'schema_status': proposal.schema_status,
             'error_category': proposal.error_category,
             'telemetry': record}
    write_new(smoke_path, smoke)
    if proposal.transport_status != 'SUCCESS':
        print(json.dumps({'status': 'SMOKE_TRANSPORT_FAILED',
                          'error_category': proposal.error_category}))
        return 2
    print(json.dumps({'status': 'SMOKE_OK', 'schema_status': proposal.schema_status}))
    return 0


# ------------------------------------------------------------------ H0 (Arm C)

def run_parse_case(delegate, out: Path, freeze: dict, index: int, case, live: list):
    """One H0 case: primary parse + at most one frozen repair re-ask.
    Deterministic order, persisted per request. Returns the case row.
    Identical control flow to the sealed C-ALR H0 run."""
    stem = f'{PREFIX}_h0_{index:03d}'
    backend = PersistedSemanticBackend(delegate, out, stem,
                                        configuration_sha256=digest(freeze),
                                        live_records=live)
    payload = {'policy_text': case.policy, 'atom_catalog': list(case.atom_catalog)}
    proposal = backend.propose(PARSE_TASK, payload, STRUCTURE_SCHEMA)
    records = list(backend.records)
    phi, status, error = None, None, None
    value = proposal.value
    if proposal.transport_status != 'SUCCESS' or proposal.schema_status != 'VALID':
        status, error = 'parse_failed', (proposal.error_category or proposal.schema_status)
    else:
        try:
            phi = v3.compile_v3_structure(value)
            status = 'ok'
        except v3.StructureInvalid as failure:
            status, error = 'compile_failed', str(failure)
    if status != 'ok':
        repair_payload = dict(payload)
        repair_payload['previous_output'] = (proposal.payload_json
                                             if proposal.payload_json is not None else None)
        repair_payload['machine_error'] = error
        repair = backend.propose(REPAIR_TASK, repair_payload, STRUCTURE_SCHEMA)
        records = list(backend.records)
        if repair.transport_status == 'SUCCESS' and repair.schema_status == 'VALID':
            try:
                phi = v3.compile_v3_structure(repair.value)
                status = 'ok_repaired'
                error = None
            except v3.StructureInvalid as failure:
                status, error = 'compile_failed_after_repair', str(failure)
        elif status == 'parse_failed':
            status = 'parse_failed_after_repair'
            error = repair.error_category or repair.schema_status
    return {'case_id': case.case_id, 'configuration_sha256': digest(freeze),
            'status': status, 'error': error, 'phi_c': phi,
            'request_records': records}


def phase_run_h0(env_file, root: Path, out: Path, minutes: float) -> int:
    freeze, cases = load_freeze(root, out)
    if not (out / f'{PREFIX}_smoke.json').exists():
        print(json.dumps({'status': 'NO_SMOKE', 'note': 'run the smoke phase first'}))
        return 2
    rows_path = out / f'{PREFIX}_predictions.json'
    if rows_path.exists():
        print(json.dumps({'status': 'ALREADY_SEALED'}))
        return 0
    load_env_file(env_file)
    config = provider_config(ClientConfig(timeout_seconds=180, max_output_tokens=2048,
                                          max_retries=0, response_format_mode='none'),
                             'bai', model='qwen3.8-flash')
    live: list = []
    delegate = DiagnosticSemanticBackend(ChatClient(config), interval_seconds=10,
                                        checkpoint=live.append)
    started = time.monotonic()
    rows = []
    for index, case in enumerate(cases):
        row_path = out / f'{PREFIX}_case_{index:03d}.json'
        if row_path.exists():
            row = json.loads(row_path.read_text(encoding='utf-8'))
            if row['case_id'] != case.case_id or row['configuration_sha256'] != digest(freeze):
                raise ValueError('cached h0 case changed')
        else:
            try:
                row = run_parse_case(delegate, out, freeze, index, case, live)
            except ProviderPause as error:
                print(json.dumps({'status': 'PROVIDER_PAUSED', 'reason': str(error),
                                  'completed': len(rows), 'total': len(cases)}), flush=True)
                return 2
            write_new(row_path, row)
        rows.append(row)
        # Transport/schema facts only: no semantic inspection during inference.
        print(json.dumps({'completed': len(rows), 'total': len(cases),
                          'case_id': case.case_id, 'status': row['status']}), flush=True)
        if time.monotonic() - started > minutes * 60:
            print(json.dumps({'status': 'PARTIAL_TIME_BUDGET', 'completed': len(rows),
                              'total': len(cases)}), flush=True)
            return 3
    prediction_rows = [{'case_id': row['case_id'], 'prediction': row['phi_c'],
                        'status': row['status']} for row in rows]
    write_new(rows_path, prediction_rows)
    seal = prediction_seal(prediction_rows, [case.case_id for case in cases],
                           architecture_commit=freeze['architecture_commit'],
                           configuration_sha256=digest(freeze))
    write_new(out / f'{PREFIX}_prediction_seal.json', seal)
    print(json.dumps({'status': 'H0_SEALED', 'cases': len(rows),
                      'ok': sum(row['status'].startswith('ok') for row in rows)}), flush=True)
    return 0

# ---------------------------------------------------------------------- score

def _base(atom: str) -> str:
    return atom[1:] if atom.startswith('!') else atom


def _clause_shape(program: dict):
    return (len(program['target_clauses']),
            sorted(len(clause) for clause in program['target_clauses']))


def _atoms_multiset(clauses):
    out = []
    for clause in clauses:
        out.extend(clause)
    return sorted(out)


def _structural_secondary(cases, programs_by_id):
    """Per-field exact-match rates against the admissible-structure set.
    Carried-inert fields (regulated_kind, facet, identity, provenance,
    quantification) are NOT_MEASURED by prereg: they are not instructed by the
    frozen prompt and are inert in the behavioral evaluator."""
    graded = [cid for cid, p in programs_by_id.items() if p is not None]
    n = len(graded)
    fields = ('modality', 'relation', 'condition_mode', 'exception_mode', 'temporal')
    measured = {}
    for field in fields:
        k = sum(1 for case in cases if case.case_id in programs_by_id
                and programs_by_id[case.case_id] is not None
                and any(programs_by_id[case.case_id][field] == gold[field]
                        for gold in case.admissible_programs))
        measured[field] = {'n_graded': n, 'match': k,
                           'rate': round(k / n, 4) if n else None}
    for name, match in (('target_clauses',
                         lambda pred, gold: (sorted(sorted(c) for c in pred) ==
                                             sorted(sorted(c) for c in gold))),
                        ('condition_literals',
                         lambda pred, gold: sorted(pred) == sorted(gold)),
                        ('exception_literals',
                         lambda pred, gold: sorted(pred) == sorted(gold))):
        k = sum(1 for case in cases if case.case_id in programs_by_id
                and programs_by_id[case.case_id] is not None
                and any(match(programs_by_id[case.case_id][name], gold[name])
                        for gold in case.admissible_programs))
        measured[name] = {'n_graded': n, 'match': k,
                          'rate': round(k / n, 4) if n else None}
    actor_cases = [case for case in cases
                   if any(gold['condition_literals'] and
                          any(lit.startswith('actor:') for lit in gold['condition_literals'])
                          for gold in case.admissible_programs)]
    actor_graded = [case for case in actor_cases if case.case_id in programs_by_id
                    and programs_by_id[case.case_id] is not None]
    actor_ok = 0
    for case in actor_graded:
        pred_actors = {lit for lit in programs_by_id[case.case_id]['condition_literals']
                       if lit.startswith('actor:')}
        if any(pred_actors == {lit for lit in gold['condition_literals']
                               if lit.startswith('actor:')}
               for gold in case.admissible_programs):
            actor_ok += 1
    measured['actor'] = {'n_actor_cases': len(actor_cases),
                         'n_graded': len(actor_graded), 'match': actor_ok,
                         'rate': round(actor_ok / len(actor_graded), 4)
                         if actor_graded else None,
                         'note': 'actor-literal correctness over actor-bearing cases; '
                                 'the structure field actor itself is prompt-frozen to '
                                 '"assistant" and not meaningfully measurable'}
    not_measured = {field: 'NOT_MEASURED' for field in
                    ('regulated_kind', 'facet', 'identity', 'provenance', 'quantification')}
    not_measured['reason'] = ('carried fields are inert in the frozen behavioral '
                              'evaluator and are not instructed by the frozen prompt; '
                              'per prereg they are reported as NOT_MEASURED, never 0')
    return {'measured': measured, 'not_measured': not_measured}


def _unsupported_counters(case, program, correct):
    """Deterministic unsupported-semantics counters (prereg section 23)."""
    golds = list(case.admissible_programs)
    out = {'invented_permission': False, 'invented_requirement': False,
           'invented_exception': False, 'invented_condition': False,
           'unsupported_restrictive_scope': False,
           'unsupported_ambiguity_third_reading': False, 'wrong_polarity': False}
    if case.ambiguous and not correct:
        out['unsupported_ambiguity_third_reading'] = True
    if program is None:
        return out
    for world in case.worlds:
        facts = frozenset(world['facts'])
        acceptable = {v3.evaluate_v3_program(gold, facts) for gold in golds}
        verdict = v3.evaluate_v3_program(program, facts)
        if verdict == 'PERMITTED' and 'PERMITTED' not in acceptable:
            out['invented_permission'] = True
        if (program['modality'] == 'REQUIREMENT' and verdict == 'VIOLATION'
                and acceptable == {'NO_VIOLATION'}):
            out['invented_requirement'] = True
    if program['exception_literals'] and all(not gold['exception_literals'] for gold in golds):
        out['invented_exception'] = True
    gold_gate_atoms = set()
    for gold in golds:
        gold_gate_atoms |= {_base(lit) for lit in gold['condition_literals']}
        gold_gate_atoms |= {_base(lit) for lit in gold['exception_literals']}
    pred_gate_atoms = {_base(lit) for lit in program['condition_literals']}
    if program['condition_literals'] and all(
            not gold['condition_literals'] and not gold['exception_literals']
            for gold in golds):
        out['invented_condition'] = True
    elif pred_gate_atoms - gold_gate_atoms:
        out['invented_condition'] = True
    gold_relations = {gold['relation'] for gold in golds}
    if (program['relation'] in ('ONLY_IF', 'IF_AND_ONLY_IF')
            and gold_relations <= {'IF', 'UNCONDITIONAL'}):
        out['unsupported_restrictive_scope'] = True
    pred_split = (len(program['target_clauses']) >= 2
                  and all(len(clause) == 1 for clause in program['target_clauses']))
    gold_merged = all(len(gold['target_clauses']) == 1 and len(gold['target_clauses'][0]) >= 2
                      for gold in golds)
    if pred_split and gold_merged:
        out['unsupported_restrictive_scope'] = True
    for gold in golds:
        for name in ('condition_literals', 'exception_literals'):
            diff = set(program[name]).symmetric_difference(set(gold[name]))
            if len(diff) == 2:
                a, b = sorted(diff)
                if a == '!' + b:
                    out['wrong_polarity'] = True
    return out


def phase_score(root: Path, out: Path) -> int:
    freeze, cases = load_freeze(root, out)
    rows = json.loads((out / f'{PREFIX}_predictions.json').read_text(encoding='utf-8'))
    seal = json.loads((out / f'{PREFIX}_prediction_seal.json').read_text(encoding='utf-8'))
    expected = prediction_seal(rows, [case.case_id for case in cases],
                               architecture_commit=freeze['architecture_commit'],
                               configuration_sha256=digest(freeze))
    if seal != expected:
        raise ValueError('prediction seal invalid; gold was not opened before seal')
    rows_by_id = {row['case_id']: row for row in rows}
    n = len(cases)

    per_case, programs_by_id = {}, {}
    for case in cases:
        row = rows_by_id[case.case_id]
        phi = row['prediction']
        correct, per_world, program = False, None, None
        if phi is not None:
            correct, per_world, program = v3.score_candidate_structure(
                dict(phi), case.worlds, case.admissible_programs)
        per_case[case.case_id] = {'correct': correct, 'per_world': per_world,
                                  'program': program, 'status': row['status']}
        programs_by_id[case.case_id] = program

    correct_count = sum(entry['correct'] for entry in per_case.values())
    overall = correct_count / n
    ci_lo, ci_hi = wilson_ci(correct_count, n)
    statuses = {}
    for entry in per_case.values():
        statuses[entry['status']] = statuses.get(entry['status'], 0) + 1
    valid = sum(v for k, v in statuses.items() if k.startswith('ok'))
    validity = valid / n

    def cohort_accuracy(cohorts):
        members = [case for case in cases if case.cohort in cohorts]
        k = sum(per_case[case.case_id]['correct'] for case in members)
        return {'n': len(members), 'correct': k,
                'accuracy': round(k / len(members), 4) if members else None}

    cohorts = {'simple': cohort_accuracy({'simple'}),
               'structural_aggregate': cohort_accuracy({'structural', 'multi_clause'}),
               'nl_stress': cohort_accuracy({'nl_stress'}),
               'ambiguity': cohort_accuracy({'ambiguity'}),
               'multi_clause_detail': cohort_accuracy({'multi_clause'}),
               'structural_detail': cohort_accuracy({'structural'})}
    families = {}
    for case in cases:
        families.setdefault(case.family, [0, 0])
        families[case.family][0] += 1
        families[case.family][1] += per_case[case.case_id]['correct']
    family_metrics = {family: {'n': counts[0], 'correct': counts[1],
                               'accuracy': round(counts[1] / counts[0], 4)}
                      for family, counts in sorted(families.items())}

    secondary = _structural_secondary(cases, programs_by_id)
    unsupported = {key: 0 for key in ('invented_permission', 'invented_requirement',
                                      'invented_exception', 'invented_condition',
                                      'unsupported_restrictive_scope',
                                      'unsupported_ambiguity_third_reading',
                                      'wrong_polarity')}
    for case in cases:
        counters = _unsupported_counters(case, programs_by_id[case.case_id],
                                         per_case[case.case_id]['correct'])
        for key, fired in counters.items():
            if fired:
                unsupported[key] += 1

    gates = PHV1_GATES
    primary_pass = overall >= gates['primary']['overall_behavioral_accuracy_gte']
    cohort_pass = (cohorts['simple']['accuracy'] is not None
                   and cohorts['simple']['accuracy'] >= gates['cohort']['simple_gte']
                   and cohorts['nl_stress']['accuracy'] is not None
                   and cohorts['nl_stress']['accuracy'] >= gates['cohort']['nl_stress_gte']
                   and cohorts['structural_aggregate']['accuracy'] is not None
                   and cohorts['structural_aggregate']['accuracy'] >= gates['cohort']['structural_aggregate_gte'])
    validity_pass = validity >= gates['validity']['schema_compile_validity_gte']
    safety_pass = (unsupported['invented_permission'] / n
                   <= gates['safety']['invented_explicit_permission_case_rate_lte']
                   and unsupported['unsupported_restrictive_scope'] / n
                   <= gates['safety']['unsupported_restrictive_reading_case_rate_lte'])
    floor_n = gates['family_floor']['applies_to_families_with_n_at_least']
    floor_acc = gates['family_floor']['behavioral_accuracy_gte']
    collapsed = [family for family, metrics in family_metrics.items()
                 if metrics['n'] >= floor_n and metrics['accuracy'] < floor_acc]
    below_cohort_gate = []
    for family, metrics in family_metrics.items():
        target = {'simple': gates['cohort']['simple_gte'],
                  'nl_stress': gates['cohort']['nl_stress_gte']}.get(
                      family, gates['cohort']['structural_aggregate_gte'])
        if metrics['accuracy'] is not None and metrics['accuracy'] < target:
            below_cohort_gate.append(family)
    promote = (primary_pass and cohort_pass and validity_pass and safety_pass
               and not collapsed)
    reopen = (overall < gates['reopen']['overall_below']
              or len(collapsed) >= gates['reopen']['major_family_collapses_gte']
              or (cohorts['structural_aggregate']['accuracy'] is not None
                  and cohorts['structural_aggregate']['accuracy']
                  < gates['reopen']['structural_aggregate_below']))
    if promote:
        verdict = 'PROMOTE_TO_INTEGRATION'
    elif reopen:
        verdict = 'REOPEN_POLICY_RESEARCH'
    else:
        verdict = 'REVISE'

    tokens = 0
    latencies = []
    requests = 0
    for index, case in enumerate(cases):
        row_path = out / f'{PREFIX}_case_{index:03d}.json'
        row = json.loads(row_path.read_text(encoding='utf-8')) if row_path.exists() else {}
        for record in row.get('request_records', []):
            requests += 1
            tokens += record.get('usage', {}).get('total_tokens', 0)
            if record.get('latency_ms'):
                latencies.append(float(record['latency_ms']))

    report = {'schema_version': 'guardian-vnext-phv1-results-v1',
              'experiment': 'PHV1',
              'prereg': PREREG_DOC,
              'terminology': 'prospective frozen holdout',
              'architecture_commit': freeze['architecture_commit'],
              'freeze_sha256': file_digest(out / f'{PREFIX}_freeze.json'),
              'benchmark_sha256': freeze['benchmark_sha256'],
              'case_count': n,
              'primary_metric': {'correct': correct_count, 'n': n,
                                 'overall_behavioral_accuracy': round(overall, 4),
                                 'wilson_ci95': [round(ci_lo, 4), round(ci_hi, 4)],
                                 'ci_method': 'wilson_95_two_sided'},
              'validity': {'schema_compile_validity': round(validity, 4),
                           'ok': statuses.get('ok', 0),
                           'ok_repaired': statuses.get('ok_repaired', 0),
                           'failed': n - valid, 'statuses': statuses},
              'cohorts': cohorts,
              'families': family_metrics,
              'structural_secondary': secondary,
              'unsupported_semantics': {**unsupported,
                                        'invented_permission_rate': round(unsupported['invented_permission'] / n, 4),
                                        'unsupported_restrictive_rate': round(unsupported['unsupported_restrictive_scope'] / n, 4)},
              'gates_evaluation': {'primary_pass': primary_pass,
                                   'cohort_pass': cohort_pass,
                                   'validity_pass': validity_pass,
                                   'safety_pass': safety_pass,
                                   'family_collapse_n_at_least_8': collapsed,
                                   'families_below_their_cohort_gate': below_cohort_gate,
                                   'gates': gates},
              'verdict': verdict,
              'historical_context': {
                  'historical_arm_c': {'reported': 'about 78.1% on 142 V5-benchmark cases',
                                      'status': 'USER_REPORTED_UNVERIFIED',
                                      'note': 'sealed artifacts physically lost; '
                                              'absence-attested; different implementation'},
                  'h0_v5_recovered': {'reported': '136/142 = 95.77% behavioral accuracy',
                                      'status': 'MACHINE_VERIFIED',
                                      'note': 'controlled dev distribution (recovered V5 '
                                              'benchmark); same frozen H0 as this study'},
                  'phv1_prospective_holdout': {'reported': f'{correct_count}/{n} = '
                                                           f'{overall:.4f}',
                                               'status': 'MACHINE_VERIFIED',
                                               'note': 'NEW unseen texts; prospective '
                                                       'frozen holdout'},
                  'comparison_rule': 'three different implementations/distributions; '
                                     'NOT a unified learning curve; historical Arm C is '
                                     'not numerically comparable to current H0'},
              'research_questions': {
                  'Q1_reproduces_above_90': bool(primary_pass),
                  'Q1_overall': round(overall, 4),
                  'Q2_nl_stress_accuracy': cohorts['nl_stress']['accuracy'],
                  'Q3_degraded_families': {'collapsed': collapsed,
                                           'below_cohort_gate': below_cohort_gate},
                  'Q4_conservative_bias_generalizes': {
                      'invented_permission_cases': unsupported['invented_permission'],
                      'invented_permission_rate': round(unsupported['invented_permission'] / n, 4)},
                  'Q5_unsupported_additions': {key: round(value / n, 4)
                                               for key, value in unsupported.items()},
                  'Q6_residual_locality': 'see policy_phv1_holdout_v1_failure_audit.json '
                                          '(deterministic post-seal classification)',
                  'Q7_mature_for_composition': verdict == 'PROMOTE_TO_INTEGRATION',
                  'Q8_continue_standalone_policy_research': verdict == 'REOPEN_POLICY_RESEARCH'},
              'efficiency': {'requests': requests, 'total_tokens': tokens,
                             'median_latency_ms': (percentile(latencies, .5)
                                                   if latencies else None),
                             'p95_latency_ms': (percentile(latencies, .95)
                                                if latencies else None)},
              'failure_audit_reference': f'{PREFIX}_failure_audit.json'}
    results_path = out / f'{PREFIX}_results.json'
    if results_path.exists():
        existing = json.loads(results_path.read_text(encoding='utf-8'))
        if digest(existing) != digest(report):
            raise ValueError('results report changed on recompute')
    else:
        write_new(results_path, report)
    print(json.dumps({'experiment': 'PHV1',
                      'overall': report['primary_metric']['overall_behavioral_accuracy'],
                      'ci95': report['primary_metric']['wilson_ci95'],
                      'validity': report['validity']['schema_compile_validity'],
                      'simple': cohorts['simple']['accuracy'],
                      'structural': cohorts['structural_aggregate']['accuracy'],
                      'nl_stress': cohorts['nl_stress']['accuracy'],
                      'ambiguity': cohorts['ambiguity']['accuracy'],
                      'invented_permission': unsupported['invented_permission'],
                      'unsupported_restrictive': unsupported['unsupported_restrictive_scope'],
                      'collapsed': collapsed,
                      'verdict': verdict}), flush=True)
    return 0


# ---------------------------------------------------------------------- audit

def _axis_diffs(pred: dict, gold: dict) -> list:
    diffs = []
    if pred['modality'] != gold['modality']:
        diffs.append('modality')
    if pred['relation'] != gold['relation']:
        diffs.append('relation')
    pc, pe = set(pred['condition_literals']), set(pred['exception_literals'])
    gc, ge = set(gold['condition_literals']), set(gold['exception_literals'])
    if pc != gc or pe != ge:
        if (pc | pe) == (gc | ge) and pc != gc:
            diffs.append('condition_exception_binding')
        elif {_base(l) for l in pc} == {_base(l) for l in gc} \
                and {_base(l) for l in pe} == {_base(l) for l in ge}:
            diffs.append('negation_polarity')
        else:
            if pc != gc:
                diffs.append('condition_literals')
            if pe != ge:
                diffs.append('exception_literals')
    if pred['condition_mode'] != gold['condition_mode']:
        diffs.append('condition_mode')
    if pred['exception_mode'] != gold['exception_mode']:
        diffs.append('exception_mode')
    if _atoms_multiset(pred['target_clauses']) != _atoms_multiset(gold['target_clauses']):
        diffs.append('target_atoms')
    elif _clause_shape(pred) != _clause_shape(gold):
        diffs.append('scope_shape')
    if pred['temporal'] != gold['temporal']:
        diffs.append('temporal')
    return diffs


def phase_audit(root: Path, out: Path) -> int:
    freeze, cases = load_freeze(root, out)
    results = json.loads((out / f'{PREFIX}_results.json').read_text(encoding='utf-8'))
    rows = json.loads((out / f'{PREFIX}_predictions.json').read_text(encoding='utf-8'))
    seal = json.loads((out / f'{PREFIX}_prediction_seal.json').read_text(encoding='utf-8'))
    if seal['prediction_sha256'] != digest(rows):
        raise ValueError('prediction seal invalid')
    rows_by_id = {row['case_id']: row for row in rows}
    classes, errors = {}, []
    for case in cases:
        row = rows_by_id[case.case_id]
        phi = row['prediction']
        if phi is None:
            classification = 'representation_gap'
            best_diffs = None
        else:
            try:
                program = v3.compile_v3_structure(dict(phi))
            except v3.StructureInvalid:
                classification, best_diffs = 'representation_gap', None
                program = None
            if program is not None:
                correct, _, _ = v3.score_candidate_structure(
                    dict(phi), case.worlds, case.admissible_programs)
                if correct:
                    continue
                per_gold = [_axis_diffs(program, gold) for gold in case.admissible_programs]
                best_diffs = min(per_gold, key=lambda diffs: (len(diffs), sorted(diffs)))
                if not best_diffs:
                    classification = 'other'
                elif len(best_diffs) == 1:
                    classification = best_diffs[0]
                else:
                    classification = 'multi_axis'
        classes[classification] = classes.get(classification, 0) + 1
        entry = {'case_id': case.case_id, 'cohort': case.cohort, 'family': case.family,
                 'axes': list(case.axes), 'status': row['status'],
                 'classification': classification,
                 'diffs_vs_closest_gold': best_diffs,
                 'ambiguous': case.ambiguous,
                 'policy': case.policy}
        if phi is not None:
            _, per_world, _ = v3.score_candidate_structure(
                dict(phi), case.worlds, case.admissible_programs)
            mismatches = [w for w in (per_world or []) if not w.get('match', True)]
            entry['mismatching_worlds'] = len(mismatches)
            entry['total_worlds'] = len(case.worlds)
            if mismatches:
                entry['first_mismatch'] = mismatches[0]
        errors.append(entry)
    q6 = ('residual errors are LOCAL (single-axis) if multi_axis + '
          'representation_gap are a minority of errors; STRUCTURAL otherwise')
    multi = classes.get('multi_axis', 0) + classes.get('representation_gap', 0)
    audit = {'schema_version': 'guardian-vnext-phv1-failure-audit-v1',
             'experiment': 'PHV1',
             'results_verdict': results['verdict'],
             'results_sha256': file_digest(out / f'{PREFIX}_results.json'),
             'prediction_seal_sha256': digest(seal),
             'classification_basis': 'deterministic typed-field diff vs the closest '
                                     'admissible gold program; no LLM judge; computed '
                                     'only after seal + score',
             'error_count': len(errors),
             'classes': classes,
             'local_vs_structural': {'multi_axis_or_representation_gap': multi,
                                     'single_axis': len(errors) - multi,
                                     'reading': q6},
             'errors': errors}
    audit_path = out / f'{PREFIX}_failure_audit.json'
    if audit_path.exists():
        existing = json.loads(audit_path.read_text(encoding='utf-8'))
        if digest(existing) != digest(audit):
            raise ValueError('failure audit changed on recompute')
    else:
        write_new(audit_path, audit)
    print(json.dumps({'status': 'AUDIT_DONE', 'errors': len(errors),
                      'classes': classes}), flush=True)
    return 0


# ----------------------------------------------------------------------- main

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['freeze', 'smoke', 'run-h0', 'score', 'audit'])
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
    if args.phase == 'score':
        return phase_score(root, out)
    return phase_audit(root, out)


if __name__ == '__main__':
    raise SystemExit(main())
