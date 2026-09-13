"""Separate frozen T2 fixture stage; run only after the other API job terminates."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

from guardian_truth.llm_client import ChatClient, ClientConfig
from guardian_truth.runtime import provider_config
from guardian_truth.settings import load_env_file
from guardian_truth.vnext.experiment import PersistedSemanticBackend, ProviderPause
from guardian_truth.vnext.integrity import digest, file_digest, prediction_seal, verify_files, write_new
from guardian_truth.vnext.latency import percentile
from guardian_truth.vnext.semantic_v2 import DiagnosticSemanticBackend
from guardian_truth.vnext.stage_tool_t2_v1 import METRIC_RULES, predict_t2, summarize_t2


ROOT = Path(__file__).resolve().parents[1]


def immutable(path, value):
    if path.exists():
        if digest(json.loads(path.read_text(encoding='utf-8'))) != digest(value):
            raise ValueError('immutable artifact changed')
    else:
        write_new(path, value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['freeze', 'run'])
    parser.add_argument('--env-file', type=Path)
    args = parser.parse_args()
    output = ROOT / 'outputs/vnext'
    prefix = 'tool_t2_v1'
    freeze_path = output / (prefix + '_freeze.json')
    report_path = output / (prefix + '_results.json')
    if report_path.exists():
        raise FileExistsError('joined T2 v1 is immutable; implement a separate version')
    benchmark_path = ROOT / 'benchmarks/vnext/tool_semantics_v1.json'
    reference_path = ROOT / 'benchmarks/vnext/tool_reference_v1.py'
    benchmark = json.loads(benchmark_path.read_text(encoding='utf-8'))
    if digest(benchmark['cases']) != benchmark['cases_sha256']:
        raise ValueError('controlled benchmark changed')
    cases = [{'case_id': case['case_id'], 'input': case['input']} for case in benchmark['cases']]
    ids = [case['case_id'] for case in cases]
    definition = {'provider': 'bai', 'model': 'qwen3.8-flash', 'timeout_seconds': 180,
        'max_output_tokens': 2048, 'max_retries': 0, 'response_format_mode': 'none',
        'interval_seconds': 10, 'temperature': 0, 'metric_rules': METRIC_RULES,
        'random_seed': 260913, 'scope': 'CONTROLLED_T2_FIXTURE_CANDIDATES_ONLY', 'escalation_steps': 0}
    source_files = sorted(path.relative_to(ROOT).as_posix() for path in (ROOT / 'src/guardian_truth').rglob('*.py'))
    source_files += ['scripts/evaluate_vnext_tool_t2.py', 'benchmarks/vnext/tool_reference_v1.py']
    if args.phase == 'freeze':
        if freeze_path.exists():
            raise FileExistsError('T2 freeze already exists')
        if subprocess.run(['git', 'diff', '--quiet', 'HEAD', '--', *source_files], cwd=ROOT).returncode:
            raise ValueError('commit T2 implementation before freeze')
        if any(not subprocess.run(['git', 'ls-files', '--error-unmatch', name], cwd=ROOT, capture_output=True).returncode == 0 for name in source_files):
            raise ValueError('all frozen sources must be tracked')
        commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
        gate_path = output / 'provider_gate_v1.json'
        gate = json.loads(gate_path.read_text(encoding='utf-8'))
        if gate['status'] != 'PASSED':
            raise ValueError('development gate failed')
        write_new(freeze_path, {'schema_version': 'guardian-vnext-t2-stage-freeze-v1', 'architecture_commit': commit,
            'definition': definition, 'definition_sha256': digest(definition), 'case_ids': ids, 'case_input_sha256': digest(cases),
            'benchmark_sha256': file_digest(benchmark_path), 'source_sha256': {name: file_digest(ROOT / name) for name in source_files},
            'gate_sha256': file_digest(gate_path), 'reference_sha256': file_digest(reference_path),
            'prompt_hash_policy': 'each exact task payload/schema/messages persisted BEFORE transport',
            'frozen_utc': datetime.now(timezone.utc).isoformat()})
        print(json.dumps({'status': 'T2_FROZEN_NOT_RUN', 'cases': len(cases), 'api_requests': 0}))
        return 0
    if args.env_file is None:
        parser.error('--env-file is required for run')
    freeze = json.loads(freeze_path.read_text(encoding='utf-8'))
    if (freeze['definition_sha256'] != digest(definition) or freeze['case_ids'] != ids
        or freeze['case_input_sha256'] != digest(cases) or freeze['benchmark_sha256'] != file_digest(benchmark_path)
        or verify_files(ROOT, freeze['source_sha256'])):
        raise ValueError('frozen T2 source/configuration/input mismatch')
    reference_source = reference_path.read_text(encoding='utf-8')
    load_env_file(args.env_file)
    config = provider_config(ClientConfig(timeout_seconds=180, max_output_tokens=2048, max_retries=0,
        response_format_mode='none'), 'bai', model='qwen3.8-flash')
    live = []
    delegate = DiagnosticSemanticBackend(ChatClient(config), interval_seconds=10, checkpoint=live.append)
    rows = []
    try:
        for index, case in enumerate(cases):
            path = output / f'{prefix}_case_{index:03d}.json'
            if path.exists():
                row = json.loads(path.read_text(encoding='utf-8'))
                if row['case_id'] != case['case_id'] or row['configuration_sha256'] != digest(freeze):
                    raise ValueError('cached T2 case changed')
            else:
                backend = PersistedSemanticBackend(delegate, output, f'{prefix}_case_{index:03d}',
                    configuration_sha256=digest(freeze), live_records=live)
                row = {'case_id': case['case_id'], 'configuration_sha256': digest(freeze),
                    'prediction': predict_t2(case['input'], backend, reference_source), 'request_telemetry': backend.records}
                write_new(path, row)
            rows.append(row)
            print(json.dumps({'completed': len(rows), 'total': len(cases), 'case_id': case['case_id'],
                'effect_status': row['prediction']['semantics']['status']}), flush=True)
    except ProviderPause as error:
        print(json.dumps({'status': 'PROVIDER_PAUSED', 'reason': str(error), 'completed': len(rows)}), flush=True)
        return 2
    predictions_path, seal_path = output / (prefix + '_predictions.json'), output / (prefix + '_prediction_seal.json')
    immutable(predictions_path, rows)
    seal = prediction_seal(rows, ids, architecture_commit=freeze['architecture_commit'], configuration_sha256=digest(freeze))
    immutable(seal_path, seal)
    if digest(json.loads(predictions_path.read_text(encoding='utf-8'))) != seal['prediction_sha256']:
        raise ValueError('prediction seal invalid; no controlled gold joined')
    telemetry = [record for row in rows for record in row['request_telemetry']]
    provider = {'attempts': len(telemetry), 'transport_success': sum(row['transport_status'] == 'SUCCESS' for row in telemetry),
        'schema_valid': sum(row['schema_status'] == 'VALID' for row in telemetry),
        'latency_ms_p50': percentile([row['latency_ms'] for row in telemetry], .5),
        'latency_ms_p95': percentile([row['latency_ms'] for row in telemetry], .95),
        'token_usage': {key: sum(row['usage'].get(key, 0) for row in telemetry) for key in ('prompt_tokens', 'completion_tokens', 'total_tokens')},
        'cost': 'NOT_AUDITED'}
    report = {'experiment': prefix, 'architecture_commit': freeze['architecture_commit'],
        'freeze_sha256': file_digest(freeze_path), 'predictions_sha256': file_digest(predictions_path),
        'prediction_seal_sha256': file_digest(seal_path), 'scope': definition['scope'],
        'provider': provider, **summarize_t2(benchmark['cases'], rows)}
    write_new(report_path, report)
    write_new(output / (prefix + '_failure_audit.json'), {'experiment': prefix,
        'source_report_sha256': file_digest(report_path), 'cases': report['failure_taxonomy']})
    print(json.dumps({key: report[key] for key in ('experiment', 'case_count', 'known_true_candidate_recall', 'unsafe_trusted_effects', 'provider')}), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
