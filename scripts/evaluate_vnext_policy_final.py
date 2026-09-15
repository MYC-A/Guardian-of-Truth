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
