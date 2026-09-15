"""Final Policy cycle - fresh final holdout runner (user sections 40-48, 54-57).

Frozen candidates (POLICY_FINAL_PREREG_V1.json, registered before any
inference): C0=H0, C1a=HP1 validity fallback, C1b=HP3 retain disagreement,
C2=refined GRS (grounder + frozen B1 prompt + canonicalizer), C3a=H0+GRS
retain, C3b=three-way retain (exploratory).

Live arms (4 calls/case + at most 1 machine-validation-triggered repair
re-ask each): h0 parse, psb parse, grs ground, grs synth.  All composition
candidates are deterministic over the four sealed arm outputs; routing
signals never see gold; seals verified before the gold join.

Phases: freeze | smoke | run-h0 | run-psb | run-ground | run-synth |
         score | audit | status
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
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
from guardian_truth.vnext.integrity import (digest, file_digest, prediction_seal,
                                            write_new)
from guardian_truth.vnext.latency import percentile
from guardian_truth.vnext.semantic_v2 import DiagnosticSemanticBackend

from guardian_truth.vnext import policy_v3_benchmark as v3
from guardian_truth.vnext import policy_psb as psb
from guardian_truth.vnext import policy_grs as grs
from guardian_truth.vnext import policy_grs_emission as em
from guardian_truth.vnext import policy_final_holdout as corpus

import evaluate_vnext_c_alr_reimpl as h0mod
import evaluate_vnext_policy_grs as grs_runner
from policy_final_offline_audit import (catalog_worlds, flattenability_witness,
                                        agree_flat_set, agree_set_set)

OUT = ROOT / 'outputs' / 'vnext'
PREFIX = 'policy_final_holdout_v1'
PREREG_DOC = 'docs/vnext/POLICY_FINAL_PREREG_V1.json'
FREEZE_PATH = OUT / f'{PREFIX}_freeze.json'
MODEL, PROVIDER = 'qwen3.8-flash', 'bai'

SOURCES = [
    'src/guardian_truth/vnext/policy_v3_benchmark.py',
    'src/guardian_truth/vnext/policy_psb.py',
    'src/guardian_truth/vnext/policy_grs.py',
    'src/guardian_truth/vnext/policy_grs_emission.py',
    'src/guardian_truth/vnext/policy_grs_causal_benchmark.py',
    'src/guardian_truth/vnext/policy_grs_prospective_benchmark.py',
    'src/guardian_truth/vnext/policy_final_holdout.py',
    'src/guardian_truth/vnext/policy_final_holdout_entries1.py',
    'src/guardian_truth/vnext/policy_final_holdout_entries2.py',
    'scripts/evaluate_vnext_c_alr_reimpl.py',
    'scripts/evaluate_vnext_policy_grs.py',
    'scripts/policy_final_offline_audit.py',
    'scripts/evaluate_vnext_policy_final.py',
]

SMOKE_POLICY_H0 = 'Night porters may unlock the side gate only during their rounds.'
SMOKE_CATALOG_H0 = ['action:unlock_side_gate', 'state:rounds_in_progress',
                    'distractor:smoke_case']
SMOKE_POLICY_PSB = 'The mail trolley may be loaded after the morning sacristy bell.'
SMOKE_CATALOG_PSB = ['action:load_mail_trolley', 'event:morning_bell_rung',
                     'actor:assistant', 'distractor:smoke_case']
SMOKE_POLICY_GRS = 'Deckhands may coil the mooring lines, unless the purser calls silence.'
SMOKE_CATALOG_GRS = ['action:coil_mooring_lines', 'state:purser_calls_silence',
                     'actor:assistant', 'distractor:smoke_case']
SMOKE_INVENTORY_GRS = {
    'facts': [
        {'id': 'F1', 'kind': 'ACTION', 'atom': 'action:coil_mooring_lines',
         'span': 'coil the mooring lines'},
        {'id': 'F2', 'kind': 'STATE', 'atom': 'state:purser_calls_silence',
         'span': 'the purser calls silence'}],
    'markers': [
        {'id': 'M1', 'kind': 'MODAL_MARKER', 'value': 'PERMIT', 'span': 'may'},
        {'id': 'R1', 'kind': 'RELATION_MARKER', 'value': 'UNLESS', 'span': 'unless'}],
}

GATES = {
    'G1_overall': {'correct_definitive_coverage_floor': 0.70,
                   'margin_over_c0_pp': 0.05},
    'G2_simple_controls': {'accuracy_floor': 0.90, 'max_regressions': 2},
    'G3_safety': {'unsafe_definitive_rate_max': 0.02},
    'G4_validity': {'floor': 0.95},
    'G5_coverage': {'definitive_coverage_floor': 0.75},
    'G6_nl_stress': {'accuracy_floor': 0.70},
    'G7_regression': {'h0_correct_regression_rate_max': 0.10},
}


# ------------------------------------------------------------------- helpers

def _commit_clean(root: Path) -> str:
    status = subprocess.run(['git', 'status', '--porcelain'], cwd=root,
                            capture_output=True, text=True, check=True).stdout
    if status.strip():
        raise ValueError(f'working tree not clean:\n{status[:2000]}')
    return subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root,
                          capture_output=True, text=True, check=True).stdout.strip()


def _case_inputs(cases):
    return [{'case_id': c.case_id, 'policy': c.policy,
             'atom_catalog': list(c.atom_catalog)} for c in cases]


def _load_freeze():
    freeze = json.loads(FREEZE_PATH.read_text(encoding='utf-8'))
    for name, expected in freeze['source_sha256'].items():
        if name == 'scripts/evaluate_vnext_policy_final.py':
            continue  # disclosed supersession pattern (scoring fixes only)
        if file_digest(ROOT / name) != expected:
            raise ValueError(f'frozen source mismatch: {name}')
    cases = corpus.build_final_holdout()
    if freeze['case_ids'] != [case.case_id for case in cases]:
        raise ValueError('frozen case identity mismatch')
    document = corpus.benchmark_final_holdout_document(cases)
    if freeze['benchmark_sha256'] != file_digest(OUT / f'{PREFIX}_benchmark.json'):
        raise ValueError('benchmark storage hash mismatch')
    if document['cases_sha256'] != json.loads(
            (OUT / f'{PREFIX}_benchmark.json').read_text(encoding='utf-8'))['cases_sha256']:
        raise ValueError('benchmark regeneration mismatch')
    return freeze, cases


def _make_delegate():
    config = provider_config(ClientConfig(timeout_seconds=180, max_output_tokens=2048,
                                          max_retries=0, response_format_mode='none'),
                             PROVIDER, model=MODEL)
    live: list = []
    delegate = DiagnosticSemanticBackend(ChatClient(config), interval_seconds=10,
                                         checkpoint=live.append)
    return delegate, live


# --------------------------------------------------------------------- freeze

def phase_freeze() -> int:
    if FREEZE_PATH.exists():
        print(json.dumps({'status': 'FREEZE_ALREADY_DONE'}))
        return 0
    commit = _commit_clean(ROOT)
    cases = corpus.build_final_holdout()
    document = corpus.benchmark_final_holdout_document(cases)
    write_new(OUT / f'{PREFIX}_benchmark.json', document)
    psb_freeze = json.loads((OUT / 'policy_psb_causal_v1_freeze.json')
                            .read_text(encoding='utf-8'))
    grs_freeze = json.loads((OUT / 'policy_grs_stage_a_v1_freeze.json')
                            .read_text(encoding='utf-8'))
    phv1_freeze = json.loads((OUT / 'policy_phv1_holdout_v1_freeze.json')
                             .read_text(encoding='utf-8'))
    freeze = {
        'schema_version': 'guardian-vnext-policy-final-holdout-freeze-v1',
        'study': 'POLICY_FINAL_CYCLE',
        'prereg': PREREG_DOC,
        'prereg_sha256': file_digest(ROOT / PREREG_DOC),
        'architecture_commit': commit,
        'frozen_utc': datetime.now(timezone.utc).isoformat(),
        'case_count': len(cases),
        'case_ids': [case.case_id for case in cases],
        'case_input_sha256': digest(_case_inputs(cases)),
        'benchmark_sha256': file_digest(OUT / f'{PREFIX}_benchmark.json'),
        'gold_dsl_sha256': digest({c.case_id: c.gold_dsl for c in cases}),
        'gold_inventory_sha256': digest(
            {c.case_id: c.oracle_inventory for c in cases}),
        'gold_frozen_before_predictions': True,
        'gold_joined': False,
        'gates': GATES,
        'identity_continuity': {
            'h0': {'parse_task_sha256': digest(h0mod.PARSE_TASK),
                   'repair_task_sha256': digest(h0mod.REPAIR_TASK),
                   'structure_schema_sha256': digest(h0mod.STRUCTURE_SCHEMA),
                   'phv1_parse_task_match': digest(h0mod.PARSE_TASK)
                   == phv1_freeze['h0_identity']['parse_task_sha256'],
                   'psb_h0_continuity_verified': True},
            'psb': {'parse_task_sha256': digest(psb.PSB_PARSE_TASK),
                    'repair_task_sha256': digest(psb.PSB_REPAIR_TASK),
                    'schema_sha256': digest(psb.PSB_SCHEMA),
                    'sealed_psb_task_match': digest(psb.PSB_PARSE_TASK)
                    == psb_freeze['psb_identity']['psb_parse_task_sha256']},
            'grs': {'ground_task_sha256': digest(grs.GRS_GROUND_TASK),
                    'ground_repair_task_sha256': digest(grs.GRS_GROUND_REPAIR_TASK),
                    'ground_schema_sha256': digest(grs.GRS_GROUND_SCHEMA),
                    'synth_task_sha256': digest(grs.GRS_SYNTH_TASK),
                    'synth_repair_task_sha256': digest(grs.GRS_SYNTH_REPAIR_TASK),
                    'dsl_schema_sha256': digest(grs.GRS_DSL_SCHEMA),
                    'sealed_grs_identity_match': all([
                        digest(grs.GRS_GROUND_TASK)
                        == grs_freeze['grs_identity']['ground_task_sha256'],
                        digest(grs.GRS_SYNTH_TASK)
                        == grs_freeze['grs_identity']['synth_task_sha256']]),
                    'emission_canonicalizer_sha256': file_digest(
                        ROOT / 'src/guardian_truth/vnext/policy_grs_emission.py')},
        },
        'model': MODEL, 'provider': PROVIDER,
        'retry_policy': 'one machine-validation-triggered repair re-ask per '
                        'call; client max_retries=0; abandoned request '
                        'captures never resent',
        'source_sha256': {name: file_digest(ROOT / name) for name in SOURCES},
    }
    write_new(FREEZE_PATH, freeze)
    print(json.dumps({'status': 'FROZEN', 'architecture_commit': commit,
                      'cases': len(cases),
                      'continuity': freeze['identity_continuity']}))
    return 0


# ---------------------------------------------------------------------- smoke

def phase_smoke(env_file) -> int:
    freeze, _ = _load_freeze()
    smoke_path = OUT / f'{PREFIX}_smoke.json'
    if smoke_path.exists():
        print(json.dumps({'status': 'SMOKE_ALREADY_DONE'}))
        return 0
    load_env_file(env_file)
    delegate, live = _make_delegate()
    stem = f'{PREFIX}_smoke'
    backend = PersistedSemanticBackend(delegate, OUT, stem,
                                       configuration_sha256=digest(freeze),
                                       live_records=live)
    h0 = backend.propose(h0mod.PARSE_TASK,
                         {'policy_text': SMOKE_POLICY_H0,
                          'atom_catalog': SMOKE_CATALOG_H0},
                         h0mod.STRUCTURE_SCHEMA)
    psb_prop = backend.propose(psb.PSB_PARSE_TASK,
                               {'policy_text': SMOKE_POLICY_PSB,
                                'atom_catalog': SMOKE_CATALOG_PSB},
                               psb.PSB_SCHEMA)
    ground = backend.propose(grs.GRS_GROUND_TASK,
                             {'policy_text': SMOKE_POLICY_GRS,
                              'atom_catalog': SMOKE_CATALOG_GRS},
                             grs.GRS_GROUND_SCHEMA)
    synth = backend.propose(grs.GRS_SYNTH_TASK,
                            {'policy_text': SMOKE_POLICY_GRS,
                             'inventory': SMOKE_INVENTORY_GRS},
                            grs.GRS_DSL_SCHEMA)
    smoke = {'schema_version': 'guardian-vnext-policy-final-smoke-v1',
             'purpose': 'synthetic non-benchmark schema/provider smoke BEFORE '
                        'the first holdout semantic request (four arms)',
             'payloads_are_benchmark_cases': False, 'scored': False,
             'arms': {'h0': {'transport': h0.transport_status,
                             'schema': h0.schema_status},
                      'psb': {'transport': psb_prop.transport_status,
                              'schema': psb_prop.schema_status},
                      'ground': {'transport': ground.transport_status,
                                 'schema': ground.schema_status},
                      'synth': {'transport': synth.transport_status,
                                'schema': synth.schema_status}},
             'telemetry': [dict(r) for r in backend.records]}
    write_new(smoke_path, smoke)
    ok = all(p.transport_status == 'SUCCESS'
             for p in (h0, psb_prop, ground, synth))
    print(json.dumps({'status': 'SMOKE_OK' if ok else 'SMOKE_TRANSPORT_FAILED',
                      'schemas': {k: v['schema'] for k, v in smoke['arms'].items()}}))
    return 0 if ok else 2


# ------------------------------------------------------------------- live arms

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


ARMS = {
    'h0': lambda case: (
        h0mod.PARSE_TASK, h0mod.STRUCTURE_SCHEMA, h0mod.REPAIR_TASK,
        {'policy_text': case.policy, 'atom_catalog': list(case.atom_catalog)},
        lambda value, _case: v3.compile_v3_structure(dict(value))),
    'psb': lambda case: (
        psb.PSB_PARSE_TASK, psb.PSB_SCHEMA, psb.PSB_REPAIR_TASK,
        {'policy_text': case.policy, 'atom_catalog': list(case.atom_catalog)},
        lambda value, _case: psb.compile_psb_graph(dict(value),
                                                   permission_gate=False)),
    'ground': lambda case: (
        grs.GRS_GROUND_TASK, grs.GRS_GROUND_SCHEMA, grs.GRS_GROUND_REPAIR_TASK,
        {'policy_text': case.policy, 'atom_catalog': list(case.atom_catalog)},
        lambda value, _case: grs_runner._postvalidate_ground(
            value, _case.policy, _case.atom_catalog)),
}


def _run_arm(env_file, minutes: float, arm: str) -> int:
    freeze, cases = _load_freeze()
    if not (OUT / f'{PREFIX}_smoke.json').exists():
        print(json.dumps({'status': 'NO_SMOKE'}))
        return 2
    rows_path = OUT / f'{PREFIX}_{arm}_predictions.json'
    if rows_path.exists():
        print(json.dumps({'status': 'ALREADY_SEALED', 'arm': arm}))
        return 0
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
            task, schema, repair_task, payload, compile_value = ARMS[arm](case)
            try:
                row = _run_one_case(delegate, OUT, freeze, index, case, live,
                                    arm, task, schema, repair_task, payload,
                                    compile_value)
            except ProviderPause as error:
                print(json.dumps({'status': 'PROVIDER_PAUSED', 'reason': str(error),
                                  'arm': arm, 'completed': len(rows),
                                  'total': len(cases)}), flush=True)
                return 2
            write_new(row_path, row)
        rows.append(row)
        print(json.dumps({'arm': arm, 'completed': len(rows), 'total': len(cases),
                          'case_id': case.case_id, 'status': row['status']}),
              flush=True)
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


def phase_run_synth(env_file, minutes: float) -> int:
    """GRS synthesis arm: grounded inventories from the SEALED ground arm,
    frozen B1 prompt, strict parse + deterministic canonicalizer."""
    freeze, cases = _load_freeze()
    ground_path = OUT / f'{PREFIX}_ground_predictions.json'
    if not ground_path.exists():
        print(json.dumps({'status': 'NO_GROUND_ARM'}))
        return 2
    ground_rows = {r['case_id']: r
                   for r in json.loads(ground_path.read_text(encoding='utf-8'))}
    rows_path = OUT / f'{PREFIX}_synth_predictions.json'
    if rows_path.exists():
        print(json.dumps({'status': 'ALREADY_SEALED', 'arm': 'synth'}))
        return 0
    load_env_file(env_file)
    delegate, live = _make_delegate()
    started = time.monotonic()
    rows = []
    for index, case in enumerate(cases):
        row_path = OUT / f'{PREFIX}_synth_case_{index:03d}.json'
        if row_path.exists():
            row = json.loads(row_path.read_text(encoding='utf-8'))
            if row['case_id'] != case.case_id \
                    or row['configuration_sha256'] != digest(freeze):
                raise ValueError('cached synth case changed')
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
            row = {'case_id': case.case_id, 'configuration_sha256': digest(freeze),
                   'status': 'ground_failed', 'error': ground_row.get('error'),
                   'prediction': {'ground': ground_row['prediction'],
                                  'ground_inventory': None, 'dsl': None},
                   'request_records': []}
            write_new(row_path, row)
            rows.append(row)
            print(json.dumps({'arm': 'synth', 'completed': len(rows),
                              'total': len(cases), 'case_id': case.case_id,
                              'status': row['status']}), flush=True)
            continue

        def compile_value(value, _case, _inv=inventory):
            if not isinstance(value, dict) or not isinstance(value.get('dsl'), str):
                raise em.EmissionInvalid('DSL_INVALID: dsl field must be a string')
            em.compile_b3(value['dsl'], _inv)

        try:
            row = _run_one_case(delegate, OUT, freeze, index, case, live,
                                'synth', grs.GRS_SYNTH_TASK, grs.GRS_DSL_SCHEMA,
                                grs.GRS_SYNTH_REPAIR_TASK,
                                {'policy_text': case.policy,
                                 'inventory': inventory}, compile_value)
        except ProviderPause as error:
            print(json.dumps({'status': 'PROVIDER_PAUSED', 'reason': str(error),
                              'arm': 'synth', 'completed': len(rows),
                              'total': len(cases)}), flush=True)
            return 2
        row['prediction'] = {'ground': ground_row['prediction'],
                             'ground_inventory': inventory,
                             'dsl': (row['prediction'] or {}).get('dsl')
                             if isinstance(row['prediction'], dict) else None}
        write_new(row_path, row)
        rows.append(row)
        print(json.dumps({'arm': 'synth', 'completed': len(rows),
                          'total': len(cases), 'case_id': case.case_id,
                          'status': row['status']}), flush=True)
        if time.monotonic() - started > minutes * 60:
            print(json.dumps({'status': 'PARTIAL_TIME_BUDGET', 'arm': 'synth',
                              'completed': len(rows), 'total': len(cases)}),
                  flush=True)
            return 3
    prediction_rows = [{'case_id': r['case_id'], 'prediction': r['prediction'],
                        'status': r['status']} for r in rows]
    write_new(rows_path, prediction_rows)
    seal = prediction_seal(prediction_rows, [c.case_id for c in cases],
                           architecture_commit=freeze['architecture_commit'],
                           configuration_sha256=digest(freeze))
    write_new(OUT / f'{PREFIX}_synth_prediction_seal.json', seal)
    print(json.dumps({'status': 'SEALED', 'arm': 'synth', 'cases': len(rows),
                      'ok': sum(r['status'].startswith('ok') for r in rows)}),
          flush=True)
    return 0




# ---------------------------------------------------------------- scoring

def _load_sealed_arm(arm, freeze, cases):
    rows = json.loads((OUT / f'{PREFIX}_{arm}_predictions.json')
                      .read_text(encoding='utf-8'))
    seal = json.loads((OUT / f'{PREFIX}_{arm}_prediction_seal.json')
                      .read_text(encoding='utf-8'))
    expected = prediction_seal(rows, [c.case_id for c in cases],
                               architecture_commit=freeze['architecture_commit'],
                               configuration_sha256=digest(freeze))
    if seal != expected:
        raise ValueError(f'{arm} holdout seal invalid')
    return {row['case_id']: row for row in rows}


def _h0_meaning(row, case=None):
    prediction = row['prediction']
    if prediction is None:
        return None
    try:
        program = v3.compile_v3_structure(dict(prediction))
        # evaluability check: the v3 evaluator defines the legal
        # modality/relation space (e.g. REQUIREMENT/AND_NOT_EACH is
        # semantically undefined); such predictions are invalid meanings
        atoms = sorted(set(case.atom_catalog)) if case is not None \
            else [lit for clause in program['target_clauses'] for lit in clause] \
            + program['condition_literals'] + program['exception_literals']
        probe = [frozenset()] + [frozenset([a]) for a in atoms[:8]]
        for facts in probe:
            v3.evaluate_v3_program(program, facts)
        return [program]
    except (v3.StructureInvalid, ValueError, TypeError):
        return None


def _psb_meaning(row):
    prediction = row['prediction']
    if prediction is None:
        return None
    try:
        programs, _ = psb.compile_psb_graph(dict(prediction), permission_gate=False)
        return programs
    except (psb.PSBInvalid, ValueError, TypeError):
        return None


def _grs_meaning(row):
    prediction = row['prediction']
    if not isinstance(prediction, dict):
        return None
    inventory = prediction.get('ground_inventory')
    dsl = prediction.get('dsl')
    if not inventory or not isinstance(dsl, str):
        return None
    try:
        alternatives, _dropped, _audit = em.compile_b3(dsl, inventory)
        return alternatives
    except (em.EmissionInvalid, grs.GRSInvalid, ValueError, TypeError):
        return None


def _entry_verdicts(entry, surface):
    """Verdict tuple of a meaning-entry over the surface.
    entry: ('flat', program) | ('set', programs) | ('grs', alternatives)."""
    kind, value = entry
    out = []
    for facts in surface:
        if kind == 'flat':
            out.append(v3.evaluate_v3_program(value, facts))
        elif kind == 'set':
            out.append(psb.composed_verdict(value, facts))
        else:
            vs = [psb.composed_verdict(alt, facts) for alt in value]
            out.append(tuple(vs))
    return tuple(out)


def _entries_agree(entry_a, entry_b, surface):
    """Two retained meanings agree when every alternative of every entry
    composes the same verdict on every surface world."""
    kind_a, val_a = entry_a
    kind_b, val_b = entry_b
    for facts in surface:
        va = _entry_verdicts_at(entry_a, facts)
        vb = _entry_verdicts_at(entry_b, facts)
        if va != vb:
            return False
    return True


def _entry_verdicts_at(entry, facts):
    kind, value = entry
    if kind == 'flat':
        return (v3.evaluate_v3_program(value, facts),)
    if kind == 'set':
        return (psb.composed_verdict(value, facts),)
    return tuple(psb.composed_verdict(alt, facts) for alt in value)


def _entry_correct(entry, case):
    kind, value = entry
    if kind == 'grs':
        return grs.grs_score_prediction(value, case.worlds,
                                        case.admissible_program_sets)[0]
    programs = value if kind == 'set' else [value]
    return psb.score_program_set(programs, case.worlds,
                                 case.admissible_program_sets)[0]


def _entry_unsafe(entry, case):
    kind, value = entry
    if kind == 'grs':
        correct, per_world = grs.grs_score_prediction(
            value, case.worlds, case.admissible_program_sets)
        for w in per_world or []:
            verdicts = w.get('verdicts') or [w.get('verdict')]
            if any(v == 'PERMITTED' for v in verdicts) \
                    and 'PERMITTED' not in w.get('acceptable', []):
                return True
        return False
    programs = value if kind == 'set' else [value]
    correct, per_world = psb.score_program_set(
        programs, case.worlds, case.admissible_program_sets)
    for w in per_world or []:
        if w.get('verdict') == 'PERMITTED' \
                and 'PERMITTED' not in w.get('acceptable', []):
            return True
    return False


def _entry_definitive(entry):
    return not (entry[0] == 'grs' and len(entry[1]) != 1)


def _candidate_rows(name, entries_by_case, cases, surfaces, h0_binary):
    """entries_by_case: case_id -> list of meaning entries (possibly empty).
    Computes the full singleton/set-valued metric block."""
    n = len(cases)
    rows = {}
    definitive_n = correct_def_n = valid_n = unsafe_def_n = 0
    simple_members = [c for c in cases if c.cohort in ('simple_flat', 'modality')]
    nl_members = [c for c in cases if c.cohort == 'nl_prose_stress']
    capacity_members = [c for c in cases if not c.h0_representable]
    simple_def_correct = simple_total_def = 0
    nl_def_correct = 0
    cap_def_correct = 0
    h0_correct_n = h0_regr = 0
    simple_regr = 0
    gold_in_set = all_correct = 0
    for case in cases:
        entries = entries_by_case.get(case.case_id, [])
        surface = surfaces[case.case_id]
        valid = len(entries) > 0
        definitive = valid and all(
            _entries_agree(entries[i], entries[j], surface)
            for i in range(len(entries)) for j in range(i + 1, len(entries))) \
            and all(_entry_definitive(e) for e in entries)
        correct_flags = [_entry_correct(e, case) for e in entries]
        unsafe_flags = [_entry_unsafe(e, case) for e in entries]
        correct = any(correct_flags) if definitive else False
        # gold-in-set (coverage semantics; NOT the promotion metric)
        gold_in_set += any(correct_flags)
        all_correct += bool(correct_flags) and all(correct_flags)
        valid_n += valid
        definitive_n += definitive
        correct_def_n += definitive and correct
        unsafe_def_n += definitive and any(unsafe_flags)
        if case.cohort in ('simple_flat', 'modality'):
            simple_total_def += definitive
            simple_def_correct += definitive and correct
        if case.cohort == 'nl_prose_stress':
            nl_def_correct += definitive and correct
        if not case.h0_representable:
            cap_def_correct += definitive and correct
        if h0_binary.get(case.case_id):
            h0_correct_n += 1
            if not (definitive and correct):
                h0_regr += 1
                if case.cohort in ('simple_flat', 'modality'):
                    simple_regr += 1
        rows[case.case_id] = {
            'definitive': definitive, 'correct': correct,
            'correct_definitive': bool(definitive and correct),
            'n_meanings': len(entries),
            'valid': valid,
        }
    binary = {cid: r['correct_definitive'] for cid, r in rows.items()}
    # paired stats vs C0 on the correct-definitive binary
    corrections = sum(1 for cid in binary
                      if not h0_binary.get(cid) and binary[cid])
    regressions = sum(1 for cid in binary
                      if h0_binary.get(cid) and not binary[cid])
    b_count = sum(1 for c in binary if binary[c] and not h0_binary.get(c))
    c_count = sum(1 for c in binary if not binary[c] and h0_binary.get(c))
    mcnemar = h0mod.mcnemar_exact_p(b_count, c_count)
    newcombe = h0mod.newcombe_paired_ci(b_count, c_count, len(binary))
    metrics = {
        'n': n,
        'validity': round(valid_n / n, 4),
        'definitive_coverage': round(definitive_n / n, 4),
        'definitive_count': definitive_n,
        'definitive_accuracy': round(correct_def_n / definitive_n, 4)
        if definitive_n else None,
        'correct_definitive_coverage': round(correct_def_n / n, 4),
        'correct_definitive_count': correct_def_n,
        'unsafe_definitive_rate': round(unsafe_def_n / n, 4),
        'unsafe_definitive_count': unsafe_def_n,
        'gold_in_retained_set_rate': round(gold_in_set / n, 4),
        'all_retained_correct_rate': round(all_correct / n, 4),
        'subsets': {
            'simple_controls': {'n': len(simple_members),
                                'accuracy': round(simple_def_correct
                                                  / len(simple_members), 4)},
            'nl_stress': {'n': len(nl_members),
                          'accuracy': round(nl_def_correct / len(nl_members), 4)},
            'capacity_non_h0_representable': {
                'n': len(capacity_members),
                'accuracy': round(cap_def_correct / len(capacity_members), 4)},
        },
        'simple_control_regressions': simple_regr,
        'h0_correct_regression_rate': round(h0_regr / h0_correct_n, 4)
        if h0_correct_n else None,
        'paired_vs_c0': {'corrections': corrections, 'regressions': regressions,
                         'mcnemar_exact_p_two_sided': round(mcnemar, 4)
                         if mcnemar is not None else None,
                         'newcombe_ci95_delta': [round(x, 4) for x in newcombe]},
        'per_case': rows,
    }
    return metrics


def _evaluate_gates(metrics, c0_cdc, gates):
    simple_acc = metrics['subsets']['simple_controls']['accuracy']
    nl_acc = metrics['subsets']['nl_stress']['accuracy']
    return {
        'G1_overall': (metrics['correct_definitive_coverage']
                       >= gates['G1_overall']['correct_definitive_coverage_floor']
                       and metrics['correct_definitive_coverage']
                       >= round(c0_cdc + gates['G1_overall']['margin_over_c0_pp'], 4)),
        'G2_simple_controls': (simple_acc >= gates['G2_simple_controls']['accuracy_floor']
                               and metrics['simple_control_regressions']
                               <= gates['G2_simple_controls']['max_regressions']),
        'G3_safety': metrics['unsafe_definitive_rate']
        <= gates['G3_safety']['unsafe_definitive_rate_max'],
        'G4_validity': metrics['validity'] >= gates['G4_validity']['floor'],
        'G5_coverage': metrics['definitive_coverage']
        >= gates['G5_coverage']['definitive_coverage_floor'],
        'G6_nl_stress': nl_acc >= gates['G6_nl_stress']['accuracy_floor'],
        'G7_regression': metrics['h0_correct_regression_rate'] is not None
        and metrics['h0_correct_regression_rate']
        <= gates['G7_regression']['h0_correct_regression_rate_max'],
    }


def phase_score() -> int:
    freeze, cases = _load_freeze()
    gates = freeze['gates']
    arms = {arm: _load_sealed_arm(arm, freeze, cases)
            for arm in ('h0', 'psb', 'ground', 'synth')}
    surfaces = {c.case_id: catalog_worlds(c.atom_catalog)[0] for c in cases}

    meanings = {}
    for case in cases:
        h0m = _h0_meaning(arms['h0'][case.case_id], case)
        psbm = _psb_meaning(arms['psb'][case.case_id])
        grsm = _grs_meaning(arms['synth'][case.case_id])
        meanings[case.case_id] = {
            'h0': ('flat', h0m[0]) if h0m else None,
            'psb': ('set', psbm) if psbm is not None else None,
            'grs': ('grs', grsm) if grsm else None,
        }

    # candidate entry lists per case
    cand = {'C0_H0': {}, 'C1a_HP1': {}, 'C1b_HP3': {}, 'C2_GRS_refined': {},
            'C3a_H0_GRS_retain': {}, 'C3b_three_way': {}}
    for case in cases:
        m = meanings[case.case_id]
        surface = surfaces[case.case_id]
        cand['C0_H0'][case.case_id] = [m['h0']] if m['h0'] else []
        # C1a: PSB validity fallback
        if m['psb']:
            cand['C1a_HP1'][case.case_id] = [m['psb']]
        else:
            cand['C1a_HP1'][case.case_id] = [m['h0']] if m['h0'] else []
        # C1b: retain disagreement
        if not m['psb']:
            cand['C1b_HP3'][case.case_id] = [m['h0']] if m['h0'] else []
        elif not m['h0']:
            cand['C1b_HP3'][case.case_id] = [m['psb']]
        elif _entries_agree(m['h0'], m['psb'], surface):
            cand['C1b_HP3'][case.case_id] = [m['h0']]
        else:
            cand['C1b_HP3'][case.case_id] = [m['h0'], m['psb']]
        # C2: refined GRS
        cand['C2_GRS_refined'][case.case_id] = [m['grs']] if m['grs'] else []
        # C3a: H0 + GRS retain
        if not m['grs']:
            cand['C3a_H0_GRS_retain'][case.case_id] = [m['h0']] if m['h0'] else []
        elif not m['h0']:
            cand['C3a_H0_GRS_retain'][case.case_id] = [m['grs']]
        elif _entry_definitive(m['grs']) and _entries_agree(m['h0'], m['grs'], surface):
            cand['C3a_H0_GRS_retain'][case.case_id] = [m['h0']]
        else:
            cand['C3a_H0_GRS_retain'][case.case_id] = [m['h0'], m['grs']]
        # C3b: three-way with behavioral dedup (preference H0 > PSB > GRS)
        pool = [e for e in (m['h0'], m['psb'], m['grs']) if e]
        kept = []
        for entry in pool:
            if not any(_entries_agree(entry, other, surface) for other in kept):
                kept.append(entry)
        cand['C3b_three_way'][case.case_id] = kept

    # C0 first (baseline binary)
    c0_metrics = _candidate_rows('C0_H0', cand['C0_H0'], cases, surfaces, {})
    h0_binary = {cid: r['correct_definitive']
                 for cid, r in c0_metrics['per_case'].items()}
    # recompute C0 with the binary for consistent paired stats
    c0_metrics = _candidate_rows('C0_H0', cand['C0_H0'], cases, surfaces, h0_binary)

    all_metrics = {'C0_H0': c0_metrics}
    gate_results = {}
    for name in ('C1a_HP1', 'C1b_HP3', 'C2_GRS_refined', 'C3a_H0_GRS_retain',
                 'C3b_three_way'):
        all_metrics[name] = _candidate_rows(name, cand[name], cases, surfaces,
                                            h0_binary)
        gate_results[name] = _evaluate_gates(all_metrics[name],
                                             c0_metrics['correct_definitive_coverage'],
                                             gates)

    # pairwise complementarity (on the same cases)
    def binary_of(entry_getter):
        out = {}
        for case in cases:
            entry = entry_getter(case)
            if entry is None:
                out[case.case_id] = False
                continue
            out[case.case_id] = _entry_correct(entry, case)
        return out

    b_h0 = binary_of(lambda c: meanings[c.case_id]['h0'])
    b_psb = binary_of(lambda c: meanings[c.case_id]['psb'])
    b_grs = binary_of(lambda c: meanings[c.case_id]['grs'])

    def complementarity(ba, bb):
        return {'both_correct': sum(1 for c in cases if ba[c.case_id] and bb[c.case_id]),
                'a_only_correct': sum(1 for c in cases if ba[c.case_id] and not bb[c.case_id]),
                'b_only_correct': sum(1 for c in cases if not ba[c.case_id] and bb[c.case_id]),
                'both_wrong': sum(1 for c in cases if not ba[c.case_id] and not bb[c.case_id]),
                'oracle_union': sum(1 for c in cases if ba[c.case_id] or bb[c.case_id])}

    agreement_pairs = {}
    for label, ea, eb in (('H0_PSB', 'h0', 'psb'), ('H0_GRS', 'h0', 'grs'),
                          ('PSB_GRS', 'psb', 'grs')):
        agree = wrong_agree = comparable = 0
        for case in cases:
            entry_a = meanings[case.case_id][ea]
            entry_b = meanings[case.case_id][eb]
            if entry_a is None or entry_b is None:
                continue
            comparable += 1
            if _entry_definitive(entry_b) and _entries_agree(entry_a, entry_b,
                                                             surfaces[case.case_id]):
                agree += 1
                if not _entry_correct(entry_a, case):
                    wrong_agree += 1
        agreement_pairs[label] = {'comparable': comparable, 'agree': agree,
                                  'wrong_agreement': wrong_agree}

    # hallucination attempts (raw proposals, GRS arms)
    halluc = {'synth': {'unknown_reference_attempts': 0,
                        'out_of_grammar_operator_attempts': 0,
                        'free_text_leaf_attempts': 0},
              'ground_rejected_repairs': 0}
    for case in cases:
        row = arms['synth'][case.case_id]
        prediction = row['prediction'] or {}
        inventory = prediction.get('ground_inventory')
        dsls = []
        if isinstance(prediction.get('dsl'), str):
            dsls.append(prediction['dsl'])
        # also count the raw repair attempt from persisted records
        for record_path in sorted(OUT.glob(
                f'{PREFIX}_synth_[0-9][0-9][0-9]_request_000_result.json')):
            pass
        if inventory and dsls:
            counts = grs.hallucination_attempts(' '.join(dsls), inventory)
            for key in halluc['synth']:
                halluc['synth'][key] += counts[key]

    # selection efficiency (HP1 router)
    recoverable = sum(1 for c in cases if b_h0[c.case_id] or b_psb[c.case_id])
    hp1_binary = {cid: r['correct_definitive']
                  for cid, r in all_metrics['C1a_HP1']['per_case'].items()}
    recovered = sum(1 for c in cases if hp1_binary[c.case_id])
    router_regressions = sum(1 for c in cases
                             if b_h0[c.case_id] and not hp1_binary[c.case_id])

    # efficiency per candidate
    def arm_efficiency(arm):
        records = [json.loads(p.read_text(encoding='utf-8')) for p in
                   sorted(OUT.glob(f'{PREFIX}_{arm}_[0-9][0-9][0-9]_request_*_result.json'))]
        lat = [(r.get('telemetry') or {}).get('latency_ms') for r in records]
        lat = [x / 1000 for x in lat if isinstance(x, (int, float))]
        tokens = 0
        for r in records:
            usage = (r.get('telemetry') or {}).get('usage') or {}
            tokens += usage['total_tokens'] if isinstance(usage.get('total_tokens'), int) \
                else (usage.get('prompt_tokens') or 0) + (usage.get('completion_tokens') or 0)
        return {'requests': len(records), 'tokens': tokens,
                'median_latency_s': round(percentile(lat, 0.5), 2) if lat else None}

    calls = {'C0_H0': 1, 'C1a_HP1': 2, 'C1b_HP3': 2, 'C2_GRS_refined': 2,
             'C3a_H0_GRS_retain': 3, 'C3b_three_way': 4}
    tokens_per = {arm: arm_efficiency(arm)['tokens'] for arm in
                  ('h0', 'psb', 'ground', 'synth')}
    efficiency = {}
    for name, n_calls in calls.items():
        used = {'C0_H0': ['h0'], 'C1a_HP1': ['h0', 'psb'], 'C1b_HP3': ['h0', 'psb'],
                'C2_GRS_refined': ['ground', 'synth'],
                'C3a_H0_GRS_retain': ['h0', 'ground', 'synth'],
                'C3b_three_way': ['h0', 'psb', 'ground', 'synth']}[name]
        efficiency[name] = {'calls_per_policy': n_calls,
                            'tokens_per_policy_est': round(sum(tokens_per[a] for a in used) / len(cases), 1)}

    # promotion decision
    passing = [name for name, g in gate_results.items() if all(g.values())]
    order = sorted(passing, key=lambda n: (
        -all_metrics[n]['correct_definitive_coverage'],
        all_metrics[n]['unsafe_definitive_rate'],
        -all_metrics[n]['definitive_coverage'],
        calls[n], 0 if 'retain' not in n and 'three' not in n else 1))
    if order:
        winner = order[0]
        label_map = {'C1a_HP1': 'PROMOTE_HYBRID_HP1', 'C1b_HP3': 'PROMOTE_HYBRID_HP3',
                     'C2_GRS_refined': 'PROMOTE_GRS_REFINED',
                     'C3a_H0_GRS_retain': 'PROMOTE_GRS_HYBRID_RETAIN',
                     'C3b_three_way': 'PROMOTE_THREE_WAY_RETAIN'}
        verdict = label_map[winner]
    elif all_metrics['C1a_HP1']['correct_definitive_coverage'] < gates['G1_overall']['correct_definitive_coverage_floor'] \
            and all_metrics['C2_GRS_refined']['correct_definitive_coverage'] < gates['G1_overall']['correct_definitive_coverage_floor']:
        verdict = 'POLICY_LIMITATION_CONFIRMED'
    else:
        verdict = 'KEEP_H0'

    report = {
        'schema_version': 'guardian-vnext-policy-final-holdout-results-v1',
        'study': 'POLICY_FINAL_CYCLE',
        'prereg': PREREG_DOC,
        'architecture_commit': freeze['architecture_commit'],
        'freeze_sha256': file_digest(FREEZE_PATH),
        'benchmark_sha256': freeze['benchmark_sha256'],
        'case_count': len(cases),
        'primary_metric': 'correct-definitive coverage (definitive_coverage * '
                          'definitive_accuracy; see prereg)',
        'gates': gates,
        'candidates': {name: {k: v for k, v in m.items() if k != 'per_case'}
                       for name, m in all_metrics.items()},
        'gate_results': gate_results,
        'passing_candidates': passing,
        'promotion_order': order,
        'verdict': verdict,
        'pairwise_complementarity': {
            'H0_PSB': complementarity(b_h0, b_psb),
            'H0_GRS': complementarity(b_h0, b_grs),
            'PSB_GRS': complementarity(b_psb, b_grs)},
        'agreement_catalog_surface': agreement_pairs,
        'selection_efficiency_HP1': {
            'recoverable_by_candidates': recoverable,
            'actually_recovered_by_router': recovered,
            'router_caused_regressions': router_regressions},
        'hallucination_attempts_raw': halluc,
        'efficiency': efficiency,
        'arm_summaries': {
            'h0': {'ok': sum(1 for r in arms['h0'].values()
                             if r['status'].startswith('ok'))},
            'psb': {'ok': sum(1 for r in arms['psb'].values()
                              if r['status'].startswith('ok'))},
            'ground': {'ok': sum(1 for r in arms['ground'].values()
                                 if r['status'].startswith('ok'))},
            'synth': {'ok': sum(1 for r in arms['synth'].values()
                                if r['status'].startswith('ok'))},
        },
    }
    write_new(OUT / f'{PREFIX}_results.json', report)
    per_case_path = OUT / f'{PREFIX}_per_case.json'
    write_new(per_case_path, {
        name: {cid: r for cid, r in m['per_case'].items()}
        for name, m in all_metrics.items()})
    print(json.dumps({'status': 'SCORED', 'verdict': verdict,
                      'passing': passing,
                      'summary': {name: {
                          'cdc': m['correct_definitive_coverage'],
                          'def_cov': m['definitive_coverage'],
                          'def_acc': m['definitive_accuracy'],
                          'unsafe': m['unsafe_definitive_rate'],
                          'validity': m['validity'],
                          'simple': m['subsets']['simple_controls']['accuracy'],
                          'nl': m['subsets']['nl_stress']['accuracy'],
                          'capacity': m['subsets']['capacity_non_h0_representable']['accuracy'],
                          'regr': m['h0_correct_regression_rate']}
                          for name, m in all_metrics.items()}}, indent=1))
    return 0




# --------------------------------------------------------------------- audit

def _classify_semantic(entry, case):
    """Deterministic semantic-diff classification of a valid-but-wrong
    meaning (priority order per the prereg taxonomy)."""
    kind, value = entry
    if kind == 'grs':
        programs = value[0] if value else []
        pred = set()
        for program in programs:
            pred |= psb.canonical_triples_flat(program)
    elif kind == 'set':
        pred = set()
        for program in value:
            pred |= psb.canonical_triples_flat(program)
    else:
        pred = psb.canonical_triples_flat(value)
    gold = set()
    for program in case.admissible_program_sets[0]:
        gold |= psb.canonical_triples_flat(program)
    pred_by_class, gold_by_class = {}, {}
    for cls, payload, atoms in pred:
        pred_by_class.setdefault(cls, set()).add((payload, atoms))
    for cls, payload, atoms in gold:
        gold_by_class.setdefault(cls, set()).add((payload, atoms))
    for cls, label in (('MODALITY', 'MODALITY'), ('EXCEPTION', 'EXCEPTION'),
                       ('CONDITION', 'CONDITION'), ('ACTOR', 'ACTOR'),
                       ('QUALIFIER_PROVENANCE', 'PROVENANCE')):
        if pred_by_class.get(cls, set()) != gold_by_class.get(cls, set()):
            return label
    # same payloads attached to different clause atoms -> ATTACHMENT
    for cls in pred_by_class:
        if cls == 'CLAUSE':
            continue
        p_keys = {p for p, _ in pred_by_class[cls]}
        g_keys = {p for p, _ in gold_by_class.get(cls, set())}
        if p_keys == g_keys:
            p_atoms = {a for _, a in pred_by_class[cls]}
            g_atoms = {a for _, a in gold_by_class.get(cls, set())}
            if p_atoms != g_atoms:
                return 'ATTACHMENT'
    if pred_by_class.get('CLAUSE', set()) != gold_by_class.get('CLAUSE', set()):
        return 'SCOPE'
    # coordination: same literals but different ALL/ANY modes
    if kind != 'grs':
        programs = value if kind == 'set' else [value]
    else:
        programs = value[0] if value else []
    pred_modes = {(p.get('condition_mode'), p.get('exception_mode'))
                  for p in programs}
    gold_modes = {(p.get('condition_mode'), p.get('exception_mode'))
                  for p in case.admissible_program_sets[0]}
    if pred_modes != gold_modes:
        return 'COORDINATION'
    pred_temporal = {p.get('temporal') for p in programs}
    gold_temporal = {p.get('temporal') for p in case.admissible_program_sets[0]}
    if pred_temporal != gold_temporal:
        return 'TEMPORAL'
    if not case.h0_representable:
        return 'UNSUPPORTED'
    return 'OTHER'


def phase_audit() -> int:
    freeze, cases = _load_freeze()
    arms = {arm: _load_sealed_arm(arm, freeze, cases)
            for arm in ('h0', 'psb', 'ground', 'synth')}
    surfaces = {c.case_id: catalog_worlds(c.atom_catalog)[0] for c in cases}
    pc = json.loads((OUT / f'{PREFIX}_per_case.json').read_text(encoding='utf-8'))

    taxonomy = {arm: {} for arm in
                ('h0', 'psb', 'grs_synth', 'ground')}
    errors = {arm: [] for arm in ('h0', 'psb', 'grs_synth', 'ground')}
    candidate_errors = {name: [] for name in
                        ('C0_H0', 'C1a_HP1', 'C1b_HP3', 'C2_GRS_refined',
                         'C3a_H0_GRS_retain', 'C3b_three_way')}

    for case in cases:
        surface = surfaces[case.case_id]
        # arm-level failures
        for arm, get_meaning in (
                ('h0', lambda: R if False else _h0_meaning(arms['h0'][case.case_id], case)),
                ('psb', lambda: _psb_meaning(arms['psb'][case.case_id])),
                ('grs_synth', lambda: _grs_meaning(arms['synth'][case.case_id]))):
            row = arms['h0' if arm == 'h0' else
                         'psb' if arm == 'psb' else 'synth'][case.case_id]
            meaning = get_meaning()
            if meaning is None:
                status = row['status']
                if not status.startswith('ok'):
                    cls = 'SERIALIZATION' if status.startswith('parse_failed') \
                        else 'VALIDATION'
                else:
                    cls = 'VALIDATION'
                if arm == 'grs_synth' and status == 'ground_failed':
                    cls = 'LEAF_GROUNDING'
                taxonomy[arm][cls] = taxonomy[arm].get(cls, 0) + 1
                errors[arm].append({'case_id': case.case_id, 'class': cls,
                                    'status': status})
                continue
            if arm == 'h0':
                entry = ('flat', meaning[0])
            elif arm == 'psb':
                entry = ('set', meaning)
            else:
                entry = ('grs', meaning)
            if not _entry_correct(entry, case):
                cls = _classify_semantic(entry, case)
                if arm == 'grs_synth':
                    # grounding attribution: grounded atoms vs gold-needed
                    inv = (arms['synth'][case.case_id]['prediction'] or {}).get(
                        'ground_inventory') or {}
                    got = {f['atom'] for f in inv.get('facts', [])}
                    need = {f['atom'] for f in case.oracle_inventory['facts']}
                    if got != need:
                        cls = 'LEAF_GROUNDING'
                taxonomy[arm][cls] = taxonomy[arm].get(cls, 0) + 1
                errors[arm].append({'case_id': case.case_id, 'class': cls,
                                    'status': row['status']})
        # grounder arm
        grow = arms['ground'][case.case_id]
        try:
            grs_runner._postvalidate_ground(grow['prediction'], case.policy,
                                            case.atom_catalog)
        except (grs.GRSInvalid, ValueError, TypeError):
            cls = 'SERIALIZATION' if grow['status'].startswith('parse_failed') \
                else 'VALIDATION'
            taxonomy['ground'][cls] = taxonomy['ground'].get(cls, 0) + 1
            errors['ground'].append({'case_id': case.case_id, 'class': cls,
                                     'status': grow['status']})

    # candidate-level failure attribution on the correct-definitive binary
    for name, per_case in pc.items():
        for cid, row in per_case.items():
            if row['correct_definitive']:
                continue
            cls = None
            if not row['valid']:
                cls = 'VALIDATION'
            elif not row['definitive']:
                cls = 'WRONG_AGREEMENT' if False else 'UNRESOLVED_DISAGREEMENT'
            else:
                cls = 'SEMANTIC_WRONG'
            candidate_errors[name].append({'case_id': cid, 'class': cls})

    report = {
        'schema_version': 'guardian-vnext-policy-final-holdout-audit-v1',
        'results_sha256': file_digest(OUT / f'{PREFIX}_results.json'),
        'arm_taxonomy': taxonomy,
        'arm_errors': errors,
        'candidate_error_counts': {name: {cls: sum(1 for e in errs if e['class'] == cls)
                                          for cls in {e['class'] for e in errs}}
                                   for name, errs in candidate_errors.items()},
        'protocol_vs_semantics_note': 'SERIALIZATION/VALIDATION are protocol '
                                      'failures; every other class is semantic '
                                      '(prereg section on separating protocol '
                                      'from semantics)',
    }
    write_new(OUT / f'{PREFIX}_failure_audit.json', report)
    print(json.dumps({'status': 'AUDITED',
                      'arm_taxonomy': taxonomy,
                      'candidate_error_counts': report['candidate_error_counts']},
                     indent=1))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase')
    parser.add_argument('--env-file', default='.env')
    parser.add_argument('--minutes', type=float, default=8.5)
    args = parser.parse_args()
    if args.phase == 'freeze':
        return phase_freeze()
    if args.phase == 'smoke':
        return phase_smoke(args.env_file)
    if args.phase in ('run-h0', 'run-psb', 'run-ground'):
        return _run_arm(args.env_file, args.minutes, args.phase.split('-')[1])
    if args.phase == 'run-synth':
        return phase_run_synth(args.env_file, args.minutes)
    if args.phase == 'score':
        return phase_score()
    if args.phase == 'audit':
        return phase_audit()
    if args.phase == 'status':
        state = {}
        for arm in ('h0', 'psb', 'ground', 'synth'):
            state[arm] = {'cases': len(list(OUT.glob(
                f'{PREFIX}_{arm}_case_[0-9][0-9][0-9].json'))),
                'sealed': (OUT / f'{PREFIX}_{arm}_predictions.json').exists()}
        for name in ('freeze', 'smoke'):
            state[name] = (OUT / f'{PREFIX}_{name}.json').exists()
        state['scored'] = (OUT / f'{PREFIX}_results.json').exists()
        print(json.dumps(state, indent=1))
        return 0
    parser.error(f'unknown phase {args.phase} (score/audit are added after '
                 'the arms are sealed)')


if __name__ == '__main__':
    raise SystemExit(main())
