"""C-ALR reimplementation study: H0 conservative primary vs H2 hybrid
(span-grounded local mutation admission) on the recovered V5 benchmark.

Study preregistration: docs/vnext/C_ALR_REIMPL_STUDY_V1.json (frozen before
the first external call of this study). Phases:

  freeze   commit-clean check + benchmark/prompt/config freeze (no API calls)
  run-h0   conservative single-parse primary, one request per case (one
           deterministic repair re-ask allowed; max 2 requests per case),
           resumable per-case persisted requests, sealed before gold join
  stage-a  deterministic STOP gate on the sealed H0 predictions (no LLM)
  run-h2   span-grounded verifier requests per (case, mutation), shared by
           arms H1 (all mutations) and H2 (risk-gated subset); sealed before
           gold join; refuses to run after a Stage A' STOP
  score    deterministic gold join + exact McNemar + Newcombe paired CI +
           correction precision + regression rate + gate evaluation

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
import time

from guardian_truth.llm_client import ChatClient, ClientConfig
from guardian_truth.runtime import provider_config
from guardian_truth.settings import load_env_file
from guardian_truth.vnext.experiment import PersistedSemanticBackend, ProviderPause
from guardian_truth.vnext.integrity import digest, file_digest, prediction_seal, write_new
from guardian_truth.vnext.latency import percentile
from guardian_truth.vnext.semantic_v2 import DiagnosticSemanticBackend

from guardian_truth.vnext import policy_v3_benchmark as v3
from guardian_truth.vnext import policy_v5_benchmark as v5

ROOT = Path(__file__).resolve().parents[1]
PREFIX = 'policy_c_alr_reimpl_v1'
STUDY_DOC = 'docs/vnext/C_ALR_REIMPL_STUDY_V1.json'

PARSE_TASK = (
    "Parse ONE workplace policy into exactly ONE typed semantic structure.\n"
    "Field rules:\n"
    "- modality: PERMISSION (the text grants or allows), PROHIBITION (the text "
    "forbids or bars), REQUIREMENT (the text obliges).\n"
    "- relation: how the regulated act is gated.\n"
    "  IF: when the conditions hold the act is licensed/obligated/forbidden; "
    "when they do not hold the text stays silent (NOT a violation, and NOT permission).\n"
    "  ONLY_IF: exclusive - the act is licensed ONLY under the conditions; doing "
    "it without them is a VIOLATION.\n"
    "  IF_AND_ONLY_IF: the act is licensed exactly under the conditions and the "
    "text commits in both directions.\n"
    "  UNLESS: the conditions are exceptions carved out of an otherwise absolute rule.\n"
    "  UNCONDITIONAL: no conditions stated.\n"
    "  AND_NOT_EACH: doing BOTH targets together is forbidden; each alone is allowed.\n"
    "- target_clauses: a list of clauses; each clause is a list of atoms that are "
    "regulated TOGETHER (same act or same batch); several clauses mean the atoms "
    "are regulated SEPARATELY.\n"
    "- condition_literals and exception_literals: typed atoms copied EXACTLY from "
    "atom_catalog; prefix an atom with \"!\" only when the text negates it.\n"
    "- condition_mode/exception_mode: ALL means conjunction (every literal), ANY "
    "means disjunction (any literal).\n"
    "- temporal: BEFORE or AFTER only when the text orders the act relative to an "
    "event, else NONE.\n"
    "- WHO is allowed or forbidden to act (for example \"only the duty engineer\") "
    "goes into condition_literals as an actor: atom from atom_catalog; the actor "
    "field stays \"assistant\".\n"
    "- An act that is neither licensed nor forbidden is NO_VIOLATION, never "
    "PERMITTED: absence of prohibition is NOT permission.\n"
    "Use ONLY atoms from atom_catalog (it also contains distractor atoms; choose "
    "the ones the text actually uses). Output exactly one JSON object matching "
    "the schema."
)

REPAIR_TASK = (
    "The previous parse attempt failed machine validation. Fix it and return "
    "exactly ONE JSON object matching the schema, with the same field rules as "
    "before. The failed attempt and the machine error are included as data only."
)

VERIFIER_TASK = (
    "You are a NARROW admission verifier. You do NOT re-parse the policy, do NOT "
    "propose interpretations, and do NOT judge anything except ONE specific local "
    "change to a current reading.\n"
    "Question: does the policy TEXT positively support this specific change "
    "(proposed_value) over the current reading (current_value)?\n"
    "Verdicts:\n"
    "- SUPPORTED: the text contains a span that positively evidences the changed "
    "reading; copy that span VERBATIM into source_span.\n"
    "- CONTRADICTED: the text positively affirms the current reading as written.\n"
    "- INSUFFICIENT_SUPPORT: anything else.\n"
    "Rules: \"nothing contradicts the change\", \"the changed reading is plausible "
    "or possible\", and restating the change are NOT support. For permission or "
    "exclusivity changes, textual silence is NOT support. If you cannot quote an "
    "exact supporting span, the verdict is INSUFFICIENT_SUPPORT. source_span must "
    "be copied character-for-character from the policy text."
)

VERIFIER_REPAIR_TASK = (
    "The previous admission-verdict attempt failed machine validation. Fix it and "
    "return exactly ONE JSON object with verdict, source_span and justification, "
    "following the same rules as before. The failed attempt and the machine error "
    "are included as data only."
)

STRUCTURE_SCHEMA = {
    "type": "object",
    "properties": {
        "modality": {"type": "string",
                     "enum": ["PERMISSION", "PROHIBITION", "REQUIREMENT"]},
        "relation": {"type": "string",
                     "enum": ["IF", "ONLY_IF", "UNLESS", "UNCONDITIONAL",
                              "IF_AND_ONLY_IF", "AND_NOT_EACH"]},
        "target_clauses": {"type": "array", "minItems": 1,
                           "items": {"type": "array", "minItems": 1,
                                     "items": {"type": "string"}}},
        "condition_literals": {"type": "array", "items": {"type": "string"}},
        "exception_literals": {"type": "array", "items": {"type": "string"}},
        "condition_mode": {"type": "string", "enum": ["ALL", "ANY"]},
        "exception_mode": {"type": "string", "enum": ["ALL", "ANY"]},
        "temporal": {"type": "string", "enum": ["NONE", "BEFORE", "AFTER"]},
        "actor": {"type": "string"},
        "regulated_kind": {"type": "string"},
        "facet": {"type": "string"},
        "identity": {"type": "string"},
        "provenance": {"type": "string"},
        "quantification": {"type": "string"},
    },
    "required": ["modality", "relation", "target_clauses"],
    "additionalProperties": False,
}

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string",
                    "enum": ["SUPPORTED", "CONTRADICTED", "INSUFFICIENT_SUPPORT"]},
        "source_span": {"type": "string"},
        "justification": {"type": "string"},
    },
    "required": ["verdict", "source_span", "justification"],
    "additionalProperties": False,
}

RISK_TRIGGERS = {
    "relation": ["only", "unless", "if", "when", "where", "while", "once",
                 "after", "before", "until", "solely", "exclusively", "reserved"],
    "condition_mode": ["and", "or", "either", "both", "neither", "nor",
                       "any", "all"],
    "exception_mode": ["and", "or", "either", "both", "neither", "nor",
                       "any", "all"],
    "target_clauses": ["and", "same", "together", "one", "single", "both",
                       "separate"],
    "temporal": ["before", "after", "once", "until", "while"],
    "condition_literals": ["only", "except", "but", "rests with", "sits with",
                           "no one"],
}

MUTATION_FIELD = {
    "IF_TO_ONLY_IF": "relation", "ONLY_IF_TO_IF": "relation",
    "IF_TO_IF_AND_ONLY_IF": "relation", "ONLY_IF_TO_IF_AND_ONLY_IF": "relation",
    "IFF_TO_ONLY_IF": "relation", "IFF_TO_IF": "relation",
    "COND_ANY_TO_ALL": "condition_mode", "COND_ALL_TO_ANY": "condition_mode",
    "EXC_ANY_TO_ALL": "exception_mode", "EXC_ALL_TO_ANY": "exception_mode",
    "CLAUSE_MERGE_TO_SPLIT": "target_clauses",
    "CLAUSE_SPLIT_TO_MERGE": "target_clauses",
    "TEMPORAL_BEFORE_TO_AFTER": "temporal",
    "TEMPORAL_AFTER_TO_BEFORE": "temporal",
    "ACTOR_BEARER_SWAP": "condition_literals",
}

REL_FLIP_MAP = {
    ("IF", "ONLY_IF"): "IF_TO_ONLY_IF", ("ONLY_IF", "IF"): "ONLY_IF_TO_IF",
    ("IF", "IF_AND_ONLY_IF"): "IF_TO_IF_AND_ONLY_IF",
    ("ONLY_IF", "IF_AND_ONLY_IF"): "ONLY_IF_TO_IF_AND_ONLY_IF",
    ("IF_AND_ONLY_IF", "ONLY_IF"): "IFF_TO_ONLY_IF",
    ("IF_AND_ONLY_IF", "IF"): "IFF_TO_IF",
}

CONFIG = {'provider': 'bai', 'model': 'qwen3.8-flash', 'timeout_seconds': 180,
          'max_output_tokens': 2048, 'max_retries': 0, 'response_format_mode': 'none',
          'interval_seconds': 10, 'temperature': 0, 'reasoning_effort': 'low',
          'random_seed': 260914, 'escalation_steps': 0,
          'max_requests_per_case_h0': 2, 'max_requests_per_mutation': 2,
          'max_admitted_patches_per_case': 2,
          'one_patch_per_field': True,
          'quota_stop': ['TWO_CONSECUTIVE_RATE_LIMITS', 'THREE_CONSECUTIVE_TRANSPORT_ERRORS',
                         'LAST_16_TRANSPORT_BELOW_90_PERCENT']}

PROMPT_FREEZE = {'parse_task_sha256': digest(PARSE_TASK),
                 'repair_task_sha256': digest(REPAIR_TASK),
                 'verifier_task_sha256': digest(VERIFIER_TASK),
                 'verifier_repair_task_sha256': digest(VERIFIER_REPAIR_TASK),
                 'structure_schema_sha256': digest(STRUCTURE_SCHEMA),
                 'verdict_schema_sha256': digest(VERDICT_SCHEMA),
                 'risk_triggers_sha256': digest(RISK_TRIGGERS),
                 'mutation_catalog_sha256': digest(v3.MUTATION_CATALOG_V1)}

GATES = {'primary': {'h2_minus_h0_pp_gte': 0.04, 'paired_exact_mcnemar_p_lt': 0.05,
                     'ci_lower_bound_gte': 0.015},
         'safety': {'correction_precision_gte': 0.75, 'c_correct_regression_rate_lte': 0.03,
                    'mutation_admission_precision_gte': 0.90,
                    'unsupported_alternative_rate_lte': 0.05},
         'efficiency': {'median_extra_verifier_calls_lte': 2,
                        'p95_extra_verifier_calls_lte': 4,
                        'extra_tokens_vs_h0_multiple_lte': 2.0},
         'stage_a_stop': {'recoverable_share_lt': 0.05, 'oracle_gain_lt_pp': 0.04}}


# --------------------------------------------------------------- mutation math

def _atoms_multiset(clauses):
    out = []
    for clause in clauses:
        out.extend(clause)
    return sorted(out)


def catalog_diff(program_a: dict, program_gold: dict):
    """Deterministic typed-field diff phi -> gold restricted to the frozen
    catalog AND to patch directions the engine can actually propose.
    Returns a list of mutation types (<= length checked by caller) or None
    when any difference is outside the catalog / wrong direction."""
    mutations = []

    def one(pair, table, label):
        if pair[0] != pair[1]:
            mtype = table.get(pair)
            if mtype is None:
                return None
            return mtype
        return False

    rel = one((program_a['relation'], program_gold['relation']), REL_FLIP_MAP, 'relation')
    if rel is None:
        return None
    if rel:
        mutations.append(rel)
    for field, table in (('condition_mode', {('ANY', 'ALL'): 'COND_ANY_TO_ALL',
                                             ('ALL', 'ANY'): 'COND_ALL_TO_ANY'}),
                         ('exception_mode', {('ANY', 'ALL'): 'EXC_ANY_TO_ALL',
                                             ('ALL', 'ANY'): 'EXC_ALL_TO_ANY'}),
                         ('temporal', {('BEFORE', 'AFTER'): 'TEMPORAL_BEFORE_TO_AFTER',
                                       ('AFTER', 'BEFORE'): 'TEMPORAL_AFTER_TO_BEFORE'})):
        mtype = one((program_a[field], program_gold[field]), table, field)
        if mtype is None:
            return None
        if mtype:
            mutations.append(mtype)
    for field in ('modality', 'actor', 'regulated_kind', 'facet', 'identity',
                  'provenance', 'quantification', 'exception_literals'):
        if program_a[field] != program_gold[field]:
            return None
    if _atoms_multiset(program_a['target_clauses']) != _atoms_multiset(
            program_gold['target_clauses']):
        return None
    shape_a = (len(program_a['target_clauses']),
               sorted(len(c) for c in program_a['target_clauses']))
    shape_g = (len(program_gold['target_clauses']),
               sorted(len(c) for c in program_gold['target_clauses']))
    if shape_a != shape_g:
        if len(program_a['target_clauses']) == 1 and len(program_a['target_clauses'][0]) >= 2 \
                and all(len(c) == 1 for c in program_gold['target_clauses']):
            mutations.append('CLAUSE_MERGE_TO_SPLIT')
        elif len(program_gold['target_clauses']) == 1 and len(program_gold['target_clauses'][0]) >= 2 \
                and all(len(c) == 1 for c in program_a['target_clauses']):
            mutations.append('CLAUSE_SPLIT_TO_MERGE')
        else:
            return None
    cond_a, cond_g = set(program_a['condition_literals']), set(program_gold['condition_literals'])
    if cond_a != cond_g:
        actor_a = {lit for lit in cond_a if lit.startswith('actor:')}
        actor_g = {lit for lit in cond_g if lit.startswith('actor:')}
        # engine ACTOR_BEARER_SWAP replaces one actor literal with actor:assistant
        swapped = (actor_a and actor_g == {'actor:assistant'}
                   and (cond_a - actor_a) == (cond_g - actor_g)
                   and len(actor_a) == 1)
        if swapped:
            mutations.append('ACTOR_BEARER_SWAP')
        else:
            return None
    return mutations


def risk_gated(policy_text: str, mutation_type: str) -> bool:
    field = MUTATION_FIELD[mutation_type]
    triggers = RISK_TRIGGERS[field]
    text = (policy_text or '').lower()
    return any(trigger in text for trigger in triggers)


def assemble_phi_h(program: dict, admitted: list) -> tuple[dict, list]:
    """Apply admitted proposals in catalog order; at most one patch per field
    and at most 2 patches per case. Returns (patched, applied_patches)."""
    if program is None:
        return None, []
    patched, seen_fields, applied = program, set(), []
    for proposal in admitted:
        field = MUTATION_FIELD[proposal['mutation_type']]
        if field in seen_fields or len(applied) >= 2:
            continue
        patched = v3.apply_patch(patched, proposal['patch'])
        seen_fields.add(field)
        applied.append({'mutation_type': proposal['mutation_type'], 'field': field,
                        'old_value': proposal.get('current_value'),
                        'new_value': proposal.get('proposed_value'),
                        'source_span': proposal.get('source_span')})
    return patched, applied


# ------------------------------------------------------------------ statistics

def mcnemar_exact_p(b: int, c: int) -> float:
    """Two-sided exact binomial test on discordant pairs (McNemar)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) * (0.5 ** n)
    return min(1.0, 2.0 * tail)


def _wilson(k: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = k / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - margin) / denom, (centre + margin) / denom


def newcombe_paired_ci(b: int, c: int, n: int) -> tuple[float, float]:
    """Newcombe hybrid-score CI for p10 - p01 (paired binary data)."""
    if n == 0:
        return 0.0, 0.0
    p10, p01 = b / n, c / n
    l10, u10 = _wilson(b, n)
    l01, u01 = _wilson(c, n)
    diff = p10 - p01
    lower = diff - math.sqrt((p10 - l10) ** 2 + (u01 - p01) ** 2)
    upper = diff + math.sqrt((u10 - p10) ** 2 + (p01 - l01) ** 2)
    return lower, upper


# --------------------------------------------------------------------- freeze

def build_cases(limit=None):
    cases = v5.build_v5_benchmark(seed=260915)
    if limit:
        cases = cases[:limit]
    return cases


def phase_freeze(root: Path, out: Path, limit=None) -> int:
    freeze_path = out / f'{PREFIX}_freeze.json'
    bench_path = out / f'{PREFIX}_benchmark.json'
    if freeze_path.exists():
        raise FileExistsError('freeze already exists')
    cases = build_cases(limit)
    document = v5.benchmark_v5_document(v5.build_v5_benchmark(seed=260915))
    if limit:
        document = {'schema_version': 'SMOKE_ONLY', 'cases': [case.as_dict() for case in cases]}
    sources = sorted(path.relative_to(root).as_posix()
                     for path in (root / 'src/guardian_truth/vnext').glob('policy_v*_benchmark.py'))
    sources.append('scripts/evaluate_vnext_c_alr_reimpl.py')
    if subprocess.run(['git', 'diff', '--quiet', 'HEAD', '--', *sources], cwd=root).returncode:
        raise ValueError('commit study implementation before freeze')
    for name in sources:
        if subprocess.run(['git', 'ls-files', '--error-unmatch', name], cwd=root,
                          capture_output=True).returncode:
            raise ValueError('all frozen study sources must be tracked')
    commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root, capture_output=True,
                            text=True, check=True).stdout.strip()
    write_new(bench_path, document)
    inputs = [{'case_id': case.case_id, 'policy': case.policy,
               'atom_catalog': list(case.atom_catalog)} for case in cases]
    write_new(freeze_path, {'schema_version': 'guardian-vnext-c-alr-reimpl-freeze-v1',
                            'study': STUDY_DOC,
                            'architecture_commit': commit,
                            'definition': CONFIG, 'definition_sha256': digest(CONFIG),
                            'prompt_freeze': PROMPT_FREEZE, 'gates': GATES,
                            'case_ids': [case.case_id for case in cases],
                            'case_input_sha256': digest(inputs),
                            'benchmark_sha256': file_digest(bench_path),
                            'study_doc_sha256': file_digest(root / STUDY_DOC),
                            'source_sha256': {name: file_digest(root / name) for name in sources},
                            'smoke_limit': limit,
                            'prompt_hash_policy': 'exact payload/messages/schema persisted '
                                                  'before every physical request',
                            'frozen_utc': datetime.now(timezone.utc).isoformat()})
    print(json.dumps({'status': 'FROZEN_NOT_RUN', 'cases': len(cases),
                      'commit': commit[:8]}))
    return 0


def load_freeze(root: Path, out: Path):
    freeze = json.loads((out / f'{PREFIX}_freeze.json').read_text(encoding='utf-8'))
    bench = json.loads((out / f'{PREFIX}_benchmark.json').read_text(encoding='utf-8'))
    if freeze['definition_sha256'] != digest(CONFIG) or freeze['gates'] != GATES \
            or freeze['prompt_freeze'] != PROMPT_FREEZE:
        raise ValueError('frozen study configuration mismatch')
    if freeze['benchmark_sha256'] != file_digest(out / f'{PREFIX}_benchmark.json'):
        raise ValueError('benchmark storage hash mismatch')
    cases = []
    for row in bench['cases']:
        case = v5.PolicyV5Case(case_id=row['case_id'], family=row['family'],
                               style=row['style'], policy=row['policy'],
                               atom_catalog=tuple(row['atom_catalog']),
                               ambiguous=row['ambiguous'], trap=row['trap'],
                               admissible_structures=tuple(dict(s) for s in row['admissible_structures']),
                               admissible_programs=tuple(dict(p) for p in row['admissible_programs']),
                               worlds=tuple(dict(w) for w in row['worlds']))
        cases.append(case)
    if freeze['case_ids'] != [case.case_id for case in cases]:
        raise ValueError('frozen case identity mismatch')
    inputs = [{'case_id': case.case_id, 'policy': case.policy,
               'atom_catalog': list(case.atom_catalog)} for case in cases]
    if freeze['case_input_sha256'] != digest(inputs):
        raise ValueError('case inputs changed after freeze')
    from guardian_truth.vnext.integrity import verify_files
    failures = verify_files(root, freeze['source_sha256'])
    if failures:
        raise ValueError(f'frozen source mismatch: {failures}')
    return freeze, cases


# ------------------------------------------------------------------ H0 (Arm C)

def run_parse_case(delegate, out: Path, freeze: dict, index: int, case, live: list):
    """One H0 case: primary parse + at most one repair. Deterministic order,
    persisted per request. Returns the case row."""
    stem = f'{PREFIX}_h0_{index:03d}'
    backend = PersistedSemanticBackend(delegate, out, stem,
                                        configuration_sha256=digest(freeze), live_records=live)
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
        print(json.dumps({'completed': len(rows), 'total': len(cases), 'case_id': case.case_id,
                          'status': row['status']}), flush=True)
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


# ------------------------------------------------------------- Stage A' (STOP)

def phase_stage_a(root: Path, out: Path) -> int:
    freeze, cases = load_freeze(root, out)
    rows = json.loads((out / f'{PREFIX}_predictions.json').read_text(encoding='utf-8'))
    seal = json.loads((out / f'{PREFIX}_prediction_seal.json').read_text(encoding='utf-8'))
    if seal['prediction_sha256'] != digest(rows):
        raise ValueError('h0 prediction seal invalid')
    report_path = out / f'{PREFIX}_stage_a.json'
    rows_by_id = {row['case_id']: row for row in rows}
    n, h0_correct, recoverable, classes = len(cases), 0, 0, {}
    detail = []
    for case in cases:
        row = rows_by_id[case.case_id]
        phi = row['prediction']
        correct = bool(phi) and v3.score_candidate_structure(
            dict(phi), case.worlds, case.admissible_programs)[0]
        classification = 'NOT_CLASSIFIED_CORRECT'
        if correct:
            h0_correct += 1
        else:
            best = None
            if phi is not None:
                try:
                    program = v3.compile_v3_structure(dict(phi))
                except v3.StructureInvalid:
                    program = None
                if program is not None:
                    for gold_structure in case.admissible_structures:
                        gold = v3.compile_v3_structure(dict(gold_structure))
                        mutations = catalog_diff(program, gold)
                        if mutations is None or len(mutations) > 2:
                            continue
                        patched = program
                        for mtype in mutations:
                            patch = {'relation': gold['relation'],
                                     'condition_mode': gold['condition_mode'],
                                     'exception_mode': gold['exception_mode'],
                                     'temporal': gold['temporal'],
                                     'target_clauses': gold['target_clauses'],
                                     'condition_literals': gold['condition_literals']}[MUTATION_FIELD[mtype]]
                            patched = v3.apply_patch(patched, {MUTATION_FIELD[mtype]: patch})
                        if v3.score_candidate_structure(patched, case.worlds,
                                                        case.admissible_programs)[0]:
                            best = mutations
                            break
            classification = ('LOCAL_PATCH_RECOVERABLE' if best is not None
                              else 'REQUIRES_GLOBAL_REPARSE')
            if best is not None:
                recoverable += 1
                detail.append({'case_id': case.case_id, 'family': case.family,
                               'mutations': best})
        classes[classification] = classes.get(classification, 0) + 1
    share = recoverable / n if n else 0.0
    oracle_gain = share  # perfect-patching ceiling, per registered definition
    stop_gates = GATES['stage_a_stop']
    stopped = share < stop_gates['recoverable_share_lt'] or oracle_gain < stop_gates['oracle_gain_lt_pp']
    report = {'schema_version': 'guardian-vnext-c-alr-reimpl-stage-a-v1',
              'experiment': PREFIX,
              'inputs': {'predictions_sha256': file_digest(out / f'{PREFIX}_predictions.json')},
              'summary': {'n_cases': n, 'h0_correct': h0_correct,
                          'h0_accuracy': round(h0_correct / n, 4) if n else None,
                          'recoverable': recoverable,
                          'recoverable_share': share,
                          'oracle_gain': oracle_gain,
                          'classes': classes},
              'verdict': 'REJECT_EARLY' if stopped else 'PROCEED_H2',
              'recoverable_detail': detail}
    if report_path.exists():
        existing = json.loads(report_path.read_text(encoding='utf-8'))
        if digest(existing) != digest(report):
            raise ValueError('stage-a report changed on recompute')
    else:
        write_new(report_path, report)
    print(json.dumps({'status': 'STAGE_A_DONE', 'h0_correct': h0_correct, 'n': n,
                      'recoverable': recoverable, 'share': round(share, 4),
                      'verdict': 'REJECT_EARLY' if stopped else 'PROCEED_H2'}), flush=True)
    return 0


# ------------------------------------------------------------------- H2 / H1

def run_verifier_mutation(backend, case, proposal):
    field = MUTATION_FIELD[proposal['mutation_type']]
    payload = {'policy_text': case.policy, 'mutation_type': proposal['mutation_type'],
               'description': proposal['description'], 'field': field,
               'current_value': proposal['current_value'],
               'proposed_value': proposal['proposed_value']}
    start = len(backend.records)
    attempt = backend.propose(VERIFIER_TASK, payload, VERDICT_SCHEMA)
    records = list(backend.records[start:])
    verdict = None
    if attempt.transport_status != 'SUCCESS' or attempt.schema_status != 'VALID':
        repair_payload = dict(payload)
        repair_payload['previous_output'] = (attempt.payload_json
                                             if attempt.payload_json is not None else None)
        repair_payload['machine_error'] = (attempt.error_category or attempt.schema_status)
        attempt = backend.propose(VERIFIER_REPAIR_TASK, repair_payload, VERDICT_SCHEMA)
        records = list(backend.records[start:])
        if attempt.transport_status != 'SUCCESS' or attempt.schema_status != 'VALID':
            verdict = {'verdict': 'INSUFFICIENT_SUPPORT', 'source_span': '',
                       'justification': 'machine default after failed verifier request',
                       'machine_note': 'verifier_request_failed_conservative_default'}
    if verdict is None:
        value = attempt.value
        verdict = {'verdict': value['verdict'], 'source_span': value.get('source_span', ''),
                   'justification': value.get('justification', '')}
    raw = verdict['verdict']
    span_ok = False
    if raw == 'SUPPORTED':
        span_ok = v3.span_is_verbatim(verdict['source_span'], case.policy)
        if not span_ok:
            verdict = dict(verdict)
            verdict['verdict'] = 'INSUFFICIENT_SUPPORT'
            verdict['machine_note'] = 'SPAN_NOT_VERBATIM_DOWNGRADED'
    return {'mutation_type': proposal['mutation_type'], 'field': field,
            'description': proposal['description'],
            'current_value': proposal['current_value'],
            'proposed_value': proposal['proposed_value'],
            'patch': proposal['patch'], 'risk_gated_h2': proposal['risk_gated_h2'],
            'verdict_raw': raw, 'span_verbatim': span_ok,
            'verdict_machine': verdict['verdict'], 'verifier_output': verdict,
            'request_records': records}


def phase_run_h2(env_file, root: Path, out: Path, minutes: float) -> int:
    freeze, cases = load_freeze(root, out)
    stage_a = json.loads((out / f'{PREFIX}_stage_a.json').read_text(encoding='utf-8'))
    if stage_a['verdict'] == 'REJECT_EARLY':
        print(json.dumps({'status': 'STOPPED_STAGE_A', 'note': 'no verifier request sent'}))
        return 2
    h0_rows = json.loads((out / f'{PREFIX}_predictions.json').read_text(encoding='utf-8'))
    seal = json.loads((out / f'{PREFIX}_prediction_seal.json').read_text(encoding='utf-8'))
    if seal['prediction_sha256'] != digest(h0_rows):
        raise ValueError('h0 prediction seal invalid')
    h1_path, h2_path = out / f'{PREFIX}_h1_predictions.json', out / f'{PREFIX}_h2_predictions.json'
    if h2_path.exists():
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
    h0_by_id = {row['case_id']: row for row in h0_rows}
    h1_rows, h2_rows, per_case = [], [], []
    for index, case in enumerate(cases):
        row_path = out / f'{PREFIX}_h2_case_{index:03d}.json'
        if row_path.exists():
            row = json.loads(row_path.read_text(encoding='utf-8'))
            if row['case_id'] != case.case_id:
                raise ValueError('cached h2 case changed')
        else:
            phi = h0_by_id[case.case_id]['prediction']
            program = None
            if phi is not None:
                try:
                    program = v3.compile_v3_structure(dict(phi))
                except v3.StructureInvalid:
                    program = None
            proposals = []
            if program is not None:
                for proposal in v3.propose_mutations(program):
                    field = MUTATION_FIELD[proposal['mutation_type']]
                    proposals.append({**proposal,
                                      'current_value': program[field],
                                      'proposed_value': proposal['patch'][field],
                                      'risk_gated_h2': risk_gated(case.policy,
                                                                  proposal['mutation_type'])})
            verdicts = []
            stem = f'{PREFIX}_h2v_{index:03d}'
            backend = PersistedSemanticBackend(delegate, out, stem,
                                               configuration_sha256=digest(freeze),
                                               live_records=live)
            for proposal in proposals:
                try:
                    verdicts.append(run_verifier_mutation(backend, case, proposal))
                except ProviderPause as error:
                    print(json.dumps({'status': 'PROVIDER_PAUSED', 'reason': str(error),
                                      'completed': len(per_case), 'total': len(cases)}),
                          flush=True)
                    return 2
            admitted_h1 = [dict(v, patch=v['patch']) for v in verdicts
                           if v['verdict_machine'] == 'SUPPORTED']
            admitted_h2 = [v for v in admitted_h1 if v['risk_gated_h2']]
            phi_h1, applied_h1 = assemble_phi_h(program, admitted_h1)
            phi_h2, applied_h2 = assemble_phi_h(program, admitted_h2)
            row = {'case_id': case.case_id, 'configuration_sha256': digest(freeze),
                   'phi_c': phi, 'verifier_mutations': verdicts,
                   'applied_patches_h1': applied_h1, 'applied_patches_h2': applied_h2,
                   'phi_h1': phi_h1, 'phi_h2': phi_h2,
                   'verifier_calls': sum(len(v['request_records']) for v in verdicts)}
            write_new(row_path, row)
        per_case.append(row)
        h1_rows.append({'case_id': row['case_id'], 'prediction': row['phi_h1']})
        h2_rows.append({'case_id': row['case_id'], 'prediction': row['phi_h2']})
        print(json.dumps({'completed': len(per_case), 'total': len(cases),
                          'case_id': case.case_id,
                          'mutations': len(row['verifier_mutations']),
                          'admitted_h2': len(row['applied_patches_h2'])}), flush=True)
        if time.monotonic() - started > minutes * 60:
            print(json.dumps({'status': 'PARTIAL_TIME_BUDGET', 'completed': len(per_case),
                              'total': len(cases)}), flush=True)
            return 3
    ids = [case.case_id for case in cases]
    write_new(h1_path, h1_rows)
    write_new(out / f'{PREFIX}_h1_prediction_seal.json',
              prediction_seal(h1_rows, ids, architecture_commit=freeze['architecture_commit'],
                              configuration_sha256=digest(freeze)))
    write_new(h2_path, h2_rows)
    write_new(out / f'{PREFIX}_h2_prediction_seal.json',
              prediction_seal(h2_rows, ids, architecture_commit=freeze['architecture_commit'],
                              configuration_sha256=digest(freeze)))
    print(json.dumps({'status': 'H2_H1_SEALED', 'cases': len(h2_rows)}), flush=True)
    return 0


# ---------------------------------------------------------------------- score

def _tokens(records):
    return sum(record.get('usage', {}).get('total_tokens', 0) for record in records)


def _score_arm(rows_by_id, cases, arm_key):
    per_case = {}
    for case in cases:
        row = rows_by_id[case.case_id]
        phi = row['prediction']
        correct, per_world, program = (False, None, None)
        if phi is not None:
            correct, per_world, program = v3.score_candidate_structure(
                dict(phi), case.worlds, case.admissible_programs)
        per_case[case.case_id] = {'correct': correct, 'per_world': per_world,
                                  'program': program}
    accuracy = sum(entry['correct'] for entry in per_case.values()) / len(cases)
    return per_case, accuracy


def _patch_gold_consistent(case, applied):
    """Deterministic: an applied patch is gold-consistent iff the patched field
    value in phi_h matches the same field of SOME admissible gold structure."""
    if not applied:
        return True
    for gold_structure in case.admissible_structures:
        gold = v3.compile_v3_structure(dict(gold_structure))
        if all(p['new_value'] == gold[p['field']] for p in applied):
            return True
    return False


def phase_score(root: Path, out: Path) -> int:
    freeze, cases = load_freeze(root, out)
    h0_rows = json.loads((out / f'{PREFIX}_predictions.json').read_text(encoding='utf-8'))
    h1_rows = json.loads((out / f'{PREFIX}_h1_predictions.json').read_text(encoding='utf-8'))
    h2_rows = json.loads((out / f'{PREFIX}_h2_predictions.json').read_text(encoding='utf-8'))
    for name, rows in (('h0', h0_rows), ('h1', h1_rows), ('h2', h2_rows)):
        seal_path = {'h0': out / f'{PREFIX}_prediction_seal.json',
                     'h1': out / f'{PREFIX}_h1_prediction_seal.json',
                     'h2': out / f'{PREFIX}_h2_prediction_seal.json'}[name]
        seal = json.loads(seal_path.read_text(encoding='utf-8'))
        expected = prediction_seal(rows, [case.case_id for case in cases],
                                   architecture_commit=freeze['architecture_commit'],
                                   configuration_sha256=digest(freeze))
        if seal != expected:
            raise ValueError(f'{name} prediction seal invalid; gold was not opened before seal')
    h0_by_id = {row['case_id']: row for row in h0_rows}
    h1_by_id = {row['case_id']: row for row in h1_rows}
    h2_by_id = {row['case_id']: row for row in h2_rows}
    per_h0, acc_h0 = _score_arm(h0_by_id, cases, 'h0')
    per_h1, acc_h1 = _score_arm(h1_by_id, cases, 'h1')
    per_h2, acc_h2 = _score_arm(h2_by_id, cases, 'h2')
    n = len(cases)

    def paired(per_a, per_b):
        b = sum(1 for case in cases if not per_a[case.case_id]['correct']
                and per_b[case.case_id]['correct'])
        c = sum(1 for case in cases if per_a[case.case_id]['correct']
                and not per_b[case.case_id]['correct'])
        both_wrong = sum(1 for case in cases if not per_a[case.case_id]['correct']
                         and not per_b[case.case_id]['correct'])
        both_right = n - b - c - both_wrong
        p = mcnemar_exact_p(b, c)
        lower, upper = newcombe_paired_ci(b, c, n)
        return {'recoveries_c_to_h': b, 'regressions_c_to_h': c, 'both_right': both_right,
                'both_wrong': both_wrong, 'delta_pp': round(100 * (b - c) / n, 2),
                'mcnemar_exact_p': round(p, 6),
                'ci95_paired': [round(lower, 4), round(upper, 4)]}

    paired_h2 = paired(per_h0, per_h2)
    paired_h1 = paired(per_h0, per_h1)
    c_wrong_h_right = paired_h2['recoveries_c_to_h']
    c_right_h_wrong = paired_h2['regressions_c_to_h']
    correction_precision = (c_wrong_h_right / (c_wrong_h_right + c_right_h_wrong)
                            if (c_wrong_h_right + c_right_h_wrong) else None)
    c_correct = sum(1 for case in cases if per_h0[case.case_id]['correct'])
    regression_rate = c_right_h_wrong / c_correct if c_correct else None

    # admission precision / unsupported alternative rate / efficiency from H2 rows
    admitted_total = admitted_gold_consistent = 0
    unsupported_cases = 0
    calls = []
    tokens_h0 = tokens_h2_extra = 0
    for index, case in enumerate(cases):
        row_path = out / f'{PREFIX}_h2_case_{index:03d}.json'
        row = json.loads(row_path.read_text(encoding='utf-8')) if row_path.exists() else None
        h0_row_path = out / f'{PREFIX}_case_{index:03d}.json'
        h0_row = json.loads(h0_row_path.read_text(encoding='utf-8')) if h0_row_path.exists() else {}
        tokens_h0 += _tokens(h0_row.get('request_records', []))
        if row is None:
            calls.append(0)
            continue
        calls.append(row['verifier_calls'])
        for mutation in row['verifier_mutations']:
            if mutation['verdict_machine'] == 'SUPPORTED':
                admitted_total += 1
        applied = row['applied_patches_h2']
        for mutation in row['verifier_mutations']:
            if mutation['risk_gated_h2']:
                tokens_h2_extra += _tokens(mutation['request_records'])
        if applied:
            if _patch_gold_consistent(case, applied):
                admitted_gold_consistent += len(applied)
            else:
                unsupported_cases += 1
    admission_precision = (admitted_gold_consistent / admitted_total
                           if admitted_total else None)
    unsupported_rate = unsupported_cases / n
    token_multiple = ((tokens_h0 + tokens_h2_extra) / tokens_h0) if tokens_h0 else None
    med_calls = percentile([float(x) for x in calls], .5) if calls else None
    p95_calls = percentile([float(x) for x in calls], .95) if calls else None

    primary, safety, eff = GATES['primary'], GATES['safety'], GATES['efficiency']
    primary_pass = ((acc_h2 - acc_h0) * 100 >= primary['h2_minus_h0_pp_gte']
                    and paired_h2['mcnemar_exact_p'] < primary['paired_exact_mcnemar_p_lt'])
    if not primary_pass and n:
        lower, _ = paired_h2['ci95_paired']
        primary_pass = (lower > 0 and lower >= primary['ci_lower_bound_gte'])
    safety_pass = ((correction_precision is not None
                    and correction_precision >= safety['correction_precision_gte'])
                   and (regression_rate is not None
                        and regression_rate <= safety['c_correct_regression_rate_lte'])
                   and (admission_precision is not None
                        and admission_precision >= safety['mutation_admission_precision_gte'])
                   and unsupported_rate <= safety['unsupported_alternative_rate_lte'])
    efficiency_pass = ((med_calls is not None and med_calls <= eff['median_extra_verifier_calls_lte'])
                       and (p95_calls is not None and p95_calls <= eff['p95_extra_verifier_calls_lte'])
                       and (token_multiple is not None
                            and token_multiple <= eff['extra_tokens_vs_h0_multiple_lte']))
    if primary_pass and safety_pass and efficiency_pass:
        verdict = 'KEEP'
    elif primary_pass:
        verdict = 'REVISE'
    else:
        verdict = 'REJECT'

    family_delta = {}
    for case in cases:
        family_delta.setdefault(case.family, [0, 0, 0])
        family_delta[case.family][0] += 1
        family_delta[case.family][1] += per_h0[case.case_id]['correct']
        family_delta[case.family][2] += per_h2[case.case_id]['correct']

    report = {'experiment': PREFIX, 'study': STUDY_DOC,
              'architecture_commit': freeze['architecture_commit'],
              'freeze_sha256': file_digest(out / f'{PREFIX}_freeze.json'),
              'benchmark_sha256': freeze['benchmark_sha256'],
              'case_count': n,
              'accuracy': {'h0': round(acc_h0, 4), 'h1': round(acc_h1, 4),
                          'h2': round(acc_h2, 4)},
              'paired_h2_vs_h0': paired_h2, 'paired_h1_vs_h0': paired_h1,
              'correction_precision': (round(correction_precision, 4)
                                       if correction_precision is not None else None),
              'c_correct_regression_rate': (round(regression_rate, 4)
                                            if regression_rate is not None else None),
              'mutation_admission_precision': (round(admission_precision, 4)
                                               if admission_precision is not None else None),
              'unsupported_alternative_rate': round(unsupported_rate, 4),
              'efficiency': {'median_extra_verifier_calls': med_calls,
                             'p95_extra_verifier_calls': p95_calls,
                             'tokens_h0': tokens_h0, 'tokens_h2_extra': tokens_h2_extra,
                             'extra_tokens_multiple': (round(token_multiple, 3)
                                                       if token_multiple else None)},
              'gates_evaluation': {'primary_pass': primary_pass, 'safety_pass': safety_pass,
                                   'efficiency_pass': efficiency_pass},
              'verdict': verdict,
              'family_delta_h2_minus_h0': {family: [counts[0], counts[1], counts[2],
                                                    counts[2] - counts[1]]
                                           for family, counts in family_delta.items()},
              'stage_a': json.loads((out / f'{PREFIX}_stage_a.json').read_text(
                  encoding='utf-8'))['summary']}
    results_path = out / f'{PREFIX}_results.json'
    if results_path.exists():
        existing = json.loads(results_path.read_text(encoding='utf-8'))
        if digest(existing) != digest(report):
            raise ValueError('results report changed on recompute')
    else:
        write_new(results_path, report)
    print(json.dumps({'experiment': PREFIX, 'h0': report['accuracy']['h0'],
                      'h2': report['accuracy']['h2'],
                      'paired': paired_h2, 'correction_precision': report['correction_precision'],
                      'regression_rate': report['c_correct_regression_rate'],
                      'verdict': verdict}), flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['freeze', 'run-h0', 'stage-a', 'run-h2', 'score'])
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env')
    parser.add_argument('--minutes', type=float, default=8.0)
    parser.add_argument('--repo-root', type=Path, default=ROOT)
    parser.add_argument('--out-dir', type=Path, default=ROOT / 'outputs/vnext')
    parser.add_argument('--limit', type=int, default=None,
                        help='SMOKE ONLY: first N frozen cases (selftest, never real data)')
    args = parser.parse_args()
    root, out = args.repo_root, args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    if args.phase == 'freeze':
        return phase_freeze(root, out, args.limit)
    if args.phase == 'run-h0':
        return phase_run_h0(args.env_file, root, out, args.minutes)
    if args.phase == 'stage-a':
        return phase_stage_a(root, out)
    if args.phase == 'run-h2':
        return phase_run_h2(args.env_file, root, out, args.minutes)
    return phase_score(root, out)


if __name__ == '__main__':
    raise SystemExit(main())
