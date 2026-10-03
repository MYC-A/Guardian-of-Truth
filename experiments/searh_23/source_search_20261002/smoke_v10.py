"""At most four format-only API calls; no labels or quality scores."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
from guardian_truth.action_audit.runtime import run_joint
from compile_tables_v10 import sha, write_new

DIRECTORY = ROOT / 'outputs/searh_23/v10/format_smoke'


def rows():
    system = ('⟦SYSTEM⟧\nUse values supplied by the user. Try the observation step before declining.\n'
        '[AVAILABLE TOOLS]\n- tool_a — apply an observed quantity\n    field_n: number!\n'
        '- tool_b — observe a record\n    field_x: string!\n'
        '- tool_c — route this request to another assistant\n    field_x: string!\n')
    examples = [('⟦USER⟧\nUse field_n 7.', '→ TOOL_CALL tool_a: {"field_n":7}'),
        ('⟦USER⟧\n{"field_x":"X","field_y":7}', 'What is field_y for X?'),
        ('⟦USER⟧\nPlease help with X.\n⟦ASSISTANT⟧\nI think this is impossible.', 'I cannot help with X.'),
        ('⟦USER⟧\nPlease help with X.', '→ TOOL_CALL tool_c: {"field_x":"X"}')]
    return [{'id': 'format_' + str(i), 'prompt': system + user, 'response': target} for i, (user, target) in enumerate(examples)]


def options(config):
    stages = config['stages']
    return {'root': ROOT, 'table_config': stages['policy_table'], 'audit_config': stages['action_audit'],
        **{k: v for k, v in stages['source_search'].items() if k != 'interface'}}


def prepare():
    config_path = ROOT / 'service/configs/guardian-v10.json'
    config = json.loads(config_path.read_text(encoding='utf-8'))
    inputs = rows(); packets = []
    def capture(messages):
        packets.append(messages)
        return {'status': 'UNAVAILABLE', 'reason': 'FORMAT_PREPARATION_NO_HTTP'}
    for row in inputs: run_joint(row, capture, **options(config))
    write_new(DIRECTORY / 'inputs.json', inputs)
    budget = {'phase': 'V10_FORMAT_ONLY_SMOKE', 'planned_http_attempts': 4,
        'planned_tokens_upper_bound': sum(len(json.dumps(m, ensure_ascii=False).encode()) + 8192 + 1024 for m in packets),
        'phase_overrun_multiplier': 1.2, 'maximum_calls_per_instruction': 4,
        'quality_scoring': False, 'gold_file': None, 'automatic_retries': 0,
        'whole_v10_limits': {'http_attempts': config['model_budget']['max_calls'], 'tokens': config['model_budget']['max_tokens']}}
    write_new(DIRECTORY / 'budget_approval.json', budget)
    files = list((ROOT / 'src/guardian_truth').rglob('*.py'))
    files += [Path(__file__), config_path, ROOT / 'service/runtime.py', DIRECTORY / 'inputs.json', DIRECTORY / 'budget_approval.json']
    frozen = {'status': 'FROZEN_FORMAT_ONLY_NOT_QUALITY_RUN', 'created_at': datetime.now(timezone.utc).isoformat(),
        'source_sha256': {p.relative_to(ROOT).as_posix(): sha(p) for p in files},
        'api_ledger_dir': config['api_ledger_dir'], 'api_calls_so_far_in_smoke': 0,
        'model': config['model_budget']['model'], 'provider': config['model_budget']['provider'],
        'reasoning_effort': config['model_budget']['reasoning_effort']}
    write_new(DIRECTORY / 'frozen.json', frozen)
    return {'status': frozen['status'], 'prepared_cases': len(inputs), 'api_calls': 0}


def execute():
    freeze_path = DIRECTORY / 'frozen.json'
    frozen = json.loads(freeze_path.read_text(encoding='utf-8'))
    if subprocess.check_output(['git', 'show', 'HEAD:' + freeze_path.relative_to(ROOT).as_posix()], cwd=ROOT) != freeze_path.read_bytes():
        raise ValueError('format freeze must be committed before API')
    for name, expected in frozen['source_sha256'].items():
        if sha(ROOT / name) != expected: raise ValueError('smoke source mismatch: ' + name)
    config = json.loads((ROOT / 'service/configs/guardian-v10.json').read_text(encoding='utf-8'))
    from guardian_truth.source_search.transport import ModelTransport
    transport = ModelTransport(Path(config['api_ledger_dir']), **config['model_budget'])
    before = transport.snapshot(); write_new(DIRECTORY / 'started.json', {'before': before})
    budget = json.loads((DIRECTORY / 'budget_approval.json').read_text(encoding='utf-8'))
    records, failure = [], None
    for row in json.loads((DIRECTORY / 'inputs.json').read_text(encoding='utf-8')):
        record = run_joint(row, transport, **options(config))
        write_new(DIRECTORY / (row['id'] + '.json'), record)
        if record.get('assessment') is None or record['v10']['action_audit'].get('status') == 'INVALID_AUDIT':
            failure = 'technical_assessment_or_audit_format_failure'
        after = transport.snapshot()
        cost = after['known_provider_tokens'] + after['unknown_usage_upper_bounds'] - before['known_provider_tokens'] - before['unknown_usage_upper_bounds']
        if cost > budget['planned_tokens_upper_bound'] * 1.2: failure = 'planned_phase_budget_overrun'
        records.append({'id': row['id'], 'audit_schema_status': record['v10']['action_audit']['status'],
            'assessment_present': record.get('assessment') is not None})
        if after['breaker_open'] or failure: break
    result = {'status': 'FAILED' if failure else 'FORMAT_SMOKE_COMPLETED', 'failure_reason': failure,
        'before': before, 'after': transport.snapshot(), 'format_records': records, 'quality_metrics': None,
        'gold_opened': False, 'automatic_retries': 0}
    write_new(DIRECTORY / 'result.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--freeze', action='store_true'); group.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    print(json.dumps(prepare() if args.freeze else execute(), ensure_ascii=True))
