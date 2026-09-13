"""Freeze native Goal v2, persist sequential requests, seal, then score dev gold."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from guardian_truth.llm_client import ChatClient, ClientConfig
from guardian_truth.runtime import provider_config
from guardian_truth.settings import load_env_file
from guardian_truth.vnext.experiment import PersistedSemanticBackend, ProviderPause
from guardian_truth.vnext.integrity import digest, file_digest, prediction_seal, verify_files, write_new
from guardian_truth.vnext.semantic_v2 import DiagnosticSemanticBackend
from guardian_truth.vnext.stage_goal_native_v2 import METRIC_RULES, predict_native_goal, summarize_native_goal
from scripts.evaluate_vnext_goal import baseline_x0, git_head, INCUMBENT, EXPECTED_X0


def sealed_write(path, value):
    if path.exists():
        if digest(json.loads(path.read_text(encoding='utf-8'))) != digest(value):
            raise ValueError('immutable artifact changed')
    else:
        write_new(path, value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', required=True, type=Path)
    args = parser.parse_args()
    output = ROOT / 'outputs/vnext'
    prefix = 'goal_plan_v2'
    freeze_path = output / (prefix + '_freeze.json')
    report_path = output / (prefix + '_results.json')
    if report_path.exists():
        raise FileExistsError('v2 already scored; use a separately implemented new version')
    if git_head(INCUMBENT) != EXPECTED_X0:
        raise ValueError('protected incumbent changed')
    if subprocess.run(['git', 'diff', '--quiet', 'HEAD', '--', 'src', 'scripts/evaluate_vnext_goal_native_v2.py'], cwd=ROOT).returncode:
        raise ValueError('implementation must be committed before candidate freeze')
    benchmark_path = ROOT / 'benchmarks/vnext/goal_plan_v1.json'
    benchmark = json.loads(benchmark_path.read_text(encoding='utf-8'))
    if digest(benchmark['cases']) != benchmark['cases_sha256']:
        raise ValueError('controlled benchmark changed')
    cases = [{'case_id': case['case_id'], 'input': case['input']} for case in benchmark['cases']]
    ids = [case['case_id'] for case in cases]
    gate_path = output / 'provider_gate_v1.json'
    gate = json.loads(gate_path.read_text(encoding='utf-8'))
    if gate['status'] != 'PASSED':
        raise ValueError('development provider gate failed')
    definition = {'provider': 'bai', 'model': 'qwen3.8-flash', 'timeout_seconds': 180,
        'max_output_tokens': 2048, 'max_retries': 0, 'response_format_mode': 'none',
        'interval_seconds': 10, 'temperature': 0, 'max_worlds': 4096,
        'metric_rules': METRIC_RULES, 'scope': 'CONTROLLED_GOAL_SUBSYSTEM_DEVELOPMENT',
        'escalation_steps': 0, 'random_seed': 260913, 'source_activation': None}
    source_files = sorted(path.relative_to(ROOT).as_posix() for path in (ROOT / 'src/guardian_truth').rglob('*.py'))
    source_files += ['scripts/evaluate_vnext_goal_native_v2.py', 'scripts/evaluate_vnext_goal.py']
    if freeze_path.exists():
        freeze = json.loads(freeze_path.read_text(encoding='utf-8'))
        if (freeze['definition_sha256'] != digest(definition) or freeze['case_ids'] != ids
            or freeze['case_input_sha256'] != digest(cases) or freeze['benchmark_sha256'] != file_digest(benchmark_path)
            or verify_files(ROOT, freeze['source_sha256']) or verify_files(INCUMBENT, freeze['baseline_source_sha256'])):
            raise ValueError('resume inputs or frozen implementation changed')
    else:
        freeze = {'schema_version': 'guardian-vnext-native-goal-stage-freeze-v2',
            'architecture_commit': git_head(ROOT), 'definition': definition, 'definition_sha256': digest(definition),
            'source_sha256': {name: file_digest(ROOT / name) for name in source_files},
            'baseline_source_sha256': {path.relative_to(INCUMBENT).as_posix(): file_digest(path) for path in (INCUMBENT / 'src/guardian_truth').rglob('*.py')},
            'case_ids': ids, 'case_input_sha256': digest(cases), 'benchmark_sha256': file_digest(benchmark_path),
            'gate_sha256': file_digest(gate_path),
            'recent_claim_provider_report_sha256': file_digest(output / 'claim_graph_v1_results.json'),
            'prompt_hash_policy': 'exact payload/schema/messages persisted BEFORE each request',
            'frozen_utc': datetime.now(timezone.utc).isoformat()}
        write_new(freeze_path, freeze)
    load_env_file(args.env_file)
    config = provider_config(ClientConfig(timeout_seconds=180, max_output_tokens=2048, max_retries=0,
        response_format_mode='none'), 'bai', model='qwen3.8-flash')
    live_records = []
    delegate = DiagnosticSemanticBackend(ChatClient(config), interval_seconds=10, checkpoint=live_records.append)
    predictions = []
    try:
        for index, case in enumerate(cases):
            path = output / f'{prefix}_case_{index:03d}.json'
            if path.exists():
                row = json.loads(path.read_text(encoding='utf-8'))
                if row['case_id'] != case['case_id'] or row['configuration_sha256'] != digest(freeze):
                    raise ValueError('cached case identity/configuration changed')
            else:
                backend = PersistedSemanticBackend(delegate, output, f'{prefix}_case_{index:03d}',
                    configuration_sha256=digest(freeze), live_records=live_records)
                prediction = predict_native_goal(case['input'], backend)
                row = {'case_id': case['case_id'], 'configuration_sha256': digest(freeze), 'prediction': prediction,
                    'request_telemetry': backend.records, 'baseline_x0': baseline_x0(case['input'])}
                write_new(path, row)
            predictions.append(row)
            print(json.dumps({'completed': index + 1, 'total': len(cases), 'case_id': case['case_id'],
                'goal_layer_status': row['prediction']['decision']['status'], 'requests': len(row['request_telemetry'])}), flush=True)
    except ProviderPause as error:
        print(json.dumps({'status': 'PROVIDER_PAUSED', 'reason': str(error), 'completed': len(predictions)}), flush=True)
        return 2
    predictions_path, seal_path = output / (prefix + '_predictions.json'), output / (prefix + '_prediction_seal.json')
    sealed_write(predictions_path, predictions)
    seal = prediction_seal(predictions, ids, architecture_commit=freeze['architecture_commit'], configuration_sha256=digest(freeze))
    sealed_write(seal_path, seal)
    if digest(json.loads(predictions_path.read_text(encoding='utf-8'))) != seal['prediction_sha256']:
        raise ValueError('prediction seal invalid; no dev gold joined')
    report = {'experiment': prefix, 'architecture_commit': freeze['architecture_commit'],
        'freeze_sha256': file_digest(freeze_path), 'predictions_sha256': file_digest(predictions_path),
        'prediction_seal_sha256': file_digest(seal_path), 'scope': definition['scope'],
        **summarize_native_goal(benchmark['cases'], predictions)}
    write_new(report_path, report)
    write_new(output / (prefix + '_failure_audit.json'), {'experiment': prefix,
        'source_report_sha256': file_digest(report_path), 'cases': report['failure_taxonomy']})
    print(json.dumps({key: report[key] for key in ('experiment', 'case_count', 'goal_layer', 'provider')}), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
