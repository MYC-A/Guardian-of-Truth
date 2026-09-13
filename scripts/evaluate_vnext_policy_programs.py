"""Freeze/run the observed Policy Semantics V2 regression with exact P1 baseline.

Never start concurrently with another API job. Model inputs contain only the
policy and source atom IDs, never benchmark programs, structures or worlds.
"""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

from guardian_truth.cycle2.policy_arms import blind_policy_cases, load_policy_arm_contract
from guardian_truth.cycle2.policy_semantics import load_policy_dataset
from guardian_truth.llm_client import ChatClient, ClientConfig
from guardian_truth.runtime import provider_config
from guardian_truth.settings import load_env_file
from guardian_truth.vnext.experiment import PersistedSemanticBackend, ProviderPause
from guardian_truth.vnext.integrity import digest, file_digest, prediction_seal, verify_files, write_new
from guardian_truth.vnext.latency import percentile
from guardian_truth.vnext.persisted_wire_v2 import PersistedWireClient
from guardian_truth.vnext.semantic_v2 import DiagnosticSemanticBackend
from guardian_truth.vnext.stage_policy_programs_v1 import METRIC_RULES, predict_policy_programs, summarize_programs


ROOT = Path(__file__).resolve().parents[1]
PREFIX = 'policy_programs_v1'


def immutable(path, value):
    if path.exists():
        if digest(json.loads(path.read_text(encoding='utf-8'))) != digest(value):
            raise ValueError('immutable policy artifact changed')
    else:
        write_new(path, value)


def provider_summary(records):
    latencies = [record['latency_ms'] for record in records
        if record.get('remote_outcome') != 'UNKNOWN_NO_AUTOMATIC_RETRY']
    return {'request_records': len(records),
        'unknown_remote_capture': sum(record.get('remote_outcome') == 'UNKNOWN_NO_AUTOMATIC_RETRY' for record in records),
        'transport_success': sum(record['transport_status'] == 'SUCCESS' for record in records),
        'schema_valid': sum(record['schema_status'] == 'VALID' for record in records),
        'schema_invalid': sum(record['schema_status'] == 'INVALID' for record in records),
        'latency_ms_p50': percentile(latencies, .5), 'latency_ms_p95': percentile(latencies, .95),
        'token_usage': {key: sum(record['usage'].get(key, 0) for record in records)
            for key in ('prompt_tokens', 'completion_tokens', 'total_tokens')}, 'cost': 'NOT_AUDITED'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['freeze', 'run'])
    parser.add_argument('--env-file', type=Path)
    args = parser.parse_args()
    output = ROOT / 'outputs/vnext'
    freeze_path, report_path = output / (PREFIX + '_freeze.json'), output / (PREFIX + '_results.json')
    if report_path.exists():
        raise FileExistsError('joined policy v1 is immutable; use a separate version')
    benchmark_path = ROOT / 'outputs/cycle2/policy_cases.json'
    contract_path = ROOT / 'contracts/cycle2_policy_arms_v1.json'
    # Already-observed development data: safe projection is the only model
    # input. Scoring below still occurs only after all predictions are sealed.
    dataset = load_policy_dataset(benchmark_path)
    safe_cases = blind_policy_cases(dataset)
    inputs = [asdict(case) for case in safe_cases]
    ids = [case.id for case in safe_cases]
    contract = load_policy_arm_contract(contract_path)
    definition = {'provider': 'bai', 'model': 'qwen3.8-flash', 'timeout_seconds': 180,
        'max_output_tokens': 2048, 'max_retries': 0, 'response_format_mode': 'none',
        'interval_seconds': 10, 'temperature': 0, 'random_seed': 260913, 'escalation_steps': 0,
        'baseline_reasoning_effort': contract.reasoning_effort,
        'original_baseline_transport': {'timeout_seconds': contract.timeout_seconds,
            'max_output_tokens': contract.max_output_tokens, 'interval_seconds': contract.interval_seconds},
        'transport_change': 'shared dev-stage envelope requests 2048 output tokens instead of 1024; starts spaced 10 instead of 5 seconds; semantic baseline unchanged',
        'baseline_prompt_schema': 'exact Cycle2 P1 arm_messages; no P2 invocation',
        'native_tasks': ['policy_program_hypotheses_v2', 'policy_program_missing_reading_v2'],
        'scope': 'OBSERVED_DEV_POLICY_PROGRAM_MEANING_STAGE_ONLY', 'metric_rules': METRIC_RULES,
        'quota_stop': ['TWO_CONSECUTIVE_RATE_LIMITS', 'THREE_CONSECUTIVE_TRANSPORT_ERRORS', 'LAST_16_TRANSPORT_BELOW_90_PERCENT'],
        'baseline_source_commit': '0199bf933d40f2b1fdc16a97cd3637ad9c97ced2'}
    sources = sorted(path.relative_to(ROOT).as_posix() for path in (ROOT / 'src/guardian_truth').rglob('*.py'))
    sources.append('scripts/evaluate_vnext_policy_programs.py')
    if args.phase == 'freeze':
        if freeze_path.exists():
            raise FileExistsError('policy freeze already exists')
        if subprocess.run(['git', 'diff', '--quiet', 'HEAD', '--', *sources], cwd=ROOT).returncode:
            raise ValueError('commit policy implementation before freeze')
        for name in sources:
            if subprocess.run(['git', 'ls-files', '--error-unmatch', name], cwd=ROOT, capture_output=True).returncode:
                raise ValueError('all frozen policy sources must be tracked')
        commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
        gate_path = output / 'provider_gate_v1.json'
        if json.loads(gate_path.read_text(encoding='utf-8'))['status'] != 'PASSED':
            raise ValueError('development provider gate failed')
        write_new(freeze_path, {'schema_version': 'guardian-vnext-policy-program-stage-freeze-v1',
            'architecture_commit': commit, 'definition': definition, 'definition_sha256': digest(definition),
            'case_ids': ids, 'case_input_sha256': digest(inputs), 'benchmark_sha256': file_digest(benchmark_path),
            'baseline_contract_sha256': file_digest(contract_path), 'gate_sha256': file_digest(gate_path),
            'source_sha256': {name: file_digest(ROOT / name) for name in sources},
            'prompt_hash_policy': 'exact payload/messages/schema persisted BEFORE every physical request',
            'frozen_utc': datetime.now(timezone.utc).isoformat()})
        print(json.dumps({'status': 'POLICY_PROGRAMS_FROZEN_NOT_RUN', 'cases': len(ids), 'api_requests': 0}))
        return 0
    if args.env_file is None:
        parser.error('--env-file required for run')
    freeze = json.loads(freeze_path.read_text(encoding='utf-8'))
    if (freeze['definition_sha256'] != digest(definition) or freeze['case_ids'] != ids
        or freeze['case_input_sha256'] != digest(inputs) or freeze['benchmark_sha256'] != file_digest(benchmark_path)
        or freeze['baseline_contract_sha256'] != file_digest(contract_path)
        or verify_files(ROOT, freeze['source_sha256'])):
        raise ValueError('frozen policy source/configuration/input mismatch')
    load_env_file(args.env_file)
    config = provider_config(ClientConfig(timeout_seconds=180, max_output_tokens=2048, max_retries=0,
        response_format_mode='none'), 'bai', model='qwen3.8-flash')
    live, rows = [], []
    delegate = DiagnosticSemanticBackend(ChatClient(config), interval_seconds=10, checkpoint=live.append)
    try:
        for index, case in enumerate(safe_cases):
            stem = f'{PREFIX}_case_{index:03d}'
            path = output / (stem + '.json')
            if path.exists():
                row = json.loads(path.read_text(encoding='utf-8'))
                if row['case_id'] != case.id or row['configuration_sha256'] != digest(freeze):
                    raise ValueError('cached policy case changed')
            else:
                native = PersistedSemanticBackend(delegate, output, stem + '_native',
                    configuration_sha256=digest(freeze), live_records=live)
                wire = PersistedWireClient(delegate, output, stem + '_p1', digest(freeze), live)
                predicted = predict_policy_programs(case, native, wire, contract)
                row = {'case_id': case.id, 'configuration_sha256': digest(freeze), 'prediction': predicted,
                    'native_request_telemetry': native.records, 'p1_request_telemetry': wire.records}
                write_new(path, row)
            rows.append(row)
            print(json.dumps({'completed': len(rows), 'total': len(ids), 'case_id': case.id,
                'native_candidates': len(row['prediction']['native']['hypotheses']),
                'coverage': row['prediction']['native']['coverage']['status'],
                'p1_schema_status': row['prediction']['fixed_p1']['schema_status']}), flush=True)
    except ProviderPause as error:
        print(json.dumps({'status': 'PROVIDER_PAUSED', 'reason': str(error), 'completed': len(rows)}), flush=True)
        return 2
    predictions_path, seal_path = output / (PREFIX + '_predictions.json'), output / (PREFIX + '_prediction_seal.json')
    immutable(predictions_path, rows)
    seal = prediction_seal(rows, ids, architecture_commit=freeze['architecture_commit'], configuration_sha256=digest(freeze))
    immutable(seal_path, seal)
    sealed_rows = json.loads(predictions_path.read_text(encoding='utf-8'))
    if digest(sealed_rows) != seal['prediction_sha256']:
        raise ValueError('policy prediction seal invalid; gold worlds not scored')
    native_records = [record for row in sealed_rows for record in row['native_request_telemetry']]
    p1_records = [record for row in sealed_rows for record in row['p1_request_telemetry']]
    report = {'experiment': PREFIX, 'architecture_commit': freeze['architecture_commit'],
        'freeze_sha256': file_digest(freeze_path), 'predictions_sha256': file_digest(predictions_path),
        'prediction_seal_sha256': file_digest(seal_path), 'scope': definition['scope'],
        'provider': {'native': provider_summary(native_records), 'fixed_p1': provider_summary(p1_records),
            'combined': provider_summary(native_records + p1_records)}, **summarize_programs(dataset.cases, sealed_rows)}
    write_new(report_path, report)
    write_new(output / (PREFIX + '_failure_audit.json'), {'experiment': PREFIX,
        'source_report_sha256': file_digest(report_path), 'cases': report['failure_taxonomy']})
    print(json.dumps({key: report[key] for key in ('experiment', 'case_count', 'candidate_behavior', 'fixed_p1_behavior', 'paired', 'semantic_coverage')}), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
