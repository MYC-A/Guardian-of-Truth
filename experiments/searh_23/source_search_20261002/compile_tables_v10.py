"""Freeze compiler code/requests, then run a single journaled offline batch.

Preparing never imports transport or connects to a provider. Execute requires
a committed freeze and a separate receipt from inspection of the new server.
Failures preserve raw replies and charges; there is no automatic retry.
"""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
from guardian_truth.policy_table.compile import assemble
from guardian_truth.policy_table.schema import Compilation
from guardian_truth.policy_table.segment import policy_hash
from guardian_truth.source_search.store import SourceStore

DIRECTORY = ROOT / 'outputs/searh_23/v10/compiler_preparation'
INPUTS = ROOT / 'outputs/searh_23/source_search_20261002/comparison_ids_v5/inputs.jsonl'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def records():
    return [json.loads(line) for line in (DIRECTORY / 'requests.jsonl').read_text(encoding='utf-8').splitlines()]


def prepare():
    queries = records()
    identities = {(q['policy_sha256'], q['sample_index']) for q in queries}
    if len(queries) != 12 or len(identities) != 12 or {index for _, index in identities} != {0, 1, 2}:
        raise ValueError('expected four exact policies, three distinct requests each')
    files = list((ROOT / 'src/guardian_truth/policy_table').glob('*.py'))
    files += [ROOT / 'src/guardian_truth/parsing.py', ROOT / 'src/guardian_truth/types.py',
        ROOT / 'src/guardian_truth/provenance.py', ROOT / 'src/guardian_truth/source_search/store.py',
        ROOT / 'src/guardian_truth/source_search/pipeline.py', ROOT / 'src/guardian_truth/source_search/id_contract.py',
        ROOT / 'src/guardian_truth/source_search/transport.py',
        Path(__file__), DIRECTORY / 'requests.jsonl', DIRECTORY / 'inventory.json', INPUTS]
    estimated = sum(q['request_utf8_bytes'] + 8192 + 1024 for q in queries)
    approval = {'phase': 'V10_OFFLINE_COMPILATION', 'planned_http_attempts': 12,
        'planned_tokens_upper_bound': estimated, 'phase_overrun_multiplier': 1.2,
        'whole_v10_limits': {'http_attempts': 200, 'tokens_including_unknown_bounds': 1500000},
        'automatic_retries': 0, 'technical_retries_allowed_by_instruction': 12,
        'stop_on_first_402_or_429': True, 'execution_requires_server_receipt': True}
    if estimated > 1500000: raise ValueError('compiler reservation exceeds the entire V10 budget')
    write_new(DIRECTORY / 'budget_approval.json', approval)
    freeze = {'status': 'FROZEN_COMPILER_ONLY_NOT_FINAL_DETECTOR',
        'created_at': datetime.now(timezone.utc).isoformat(),
        'source_sha256': {path.relative_to(ROOT).as_posix(): sha(path) for path in files},
        'budget_approval_sha256': sha(DIRECTORY / 'budget_approval.json'),
        'model': 'gpt-oss:120b', 'provider': 'ollama', 'reasoning_effort': 'medium',
        'max_output_tokens': 8192, 'independence': 'THREE_DISTINCT_REQUESTS_NOT_INDEPENDENT_ERROR_DISTRIBUTIONS',
        'policy_hashes': sorted({key for key, _ in identities}), 'gold_opened_by_compiler': False,
        'public46_status': 'BURNED_DEVELOPMENT_DATA',
        'api_ledger_dir': '/workspace/guardian/results/v10_api_' + hashlib.sha256(
            json.dumps({path.relative_to(ROOT).as_posix(): sha(path) for path in files}, sort_keys=True).encode()).hexdigest()[:16]}
    write_new(DIRECTORY / 'frozen.json', freeze)
    return freeze


def verify_freeze():
    freeze_path = DIRECTORY / 'frozen.json'
    freeze = json.loads(freeze_path.read_text(encoding='utf-8'))
    for relative, expected in freeze['source_sha256'].items():
        if sha(ROOT / relative) != expected: raise ValueError('compiler freeze mismatch: ' + relative)
    if sha(DIRECTORY / 'budget_approval.json') != freeze['budget_approval_sha256']:
        raise ValueError('budget approval changed after freeze')
    archived = subprocess.run(['git', 'show', 'HEAD:' + freeze_path.relative_to(ROOT).as_posix()],
        cwd=ROOT, capture_output=True, check=True).stdout
    if archived != freeze_path.read_bytes(): raise ValueError('freeze must be committed before API')
    return freeze


def execute(server_receipt):
    freeze = verify_freeze()
    receipt = json.loads(Path(server_receipt).read_text(encoding='utf-8'))
    for field in ('operating_guide_read_fully', 'python_environment_verified', 'credentials_presence_verified', 'prior_expenses_preserved'):
        if receipt.get(field) is not True: raise ValueError('new server prerequisite is missing: ' + field)
    from guardian_truth.source_search.transport import ModelTransport
    from guardian_truth.source_search.pipeline import decode_model_object
    transport = ModelTransport(Path(freeze['api_ledger_dir']), max_calls=200,
        max_tokens=1500000, max_output_tokens=freeze['max_output_tokens'], timeout=300,
        provider=freeze['provider'], model=freeze['model'], reasoning_effort=freeze['reasoning_effort'], json_mode=False)
    before = transport.snapshot()
    write_new(DIRECTORY / 'execution_started.json', {'before': before, 'compiler_freeze_sha256': sha(DIRECTORY / 'frozen.json'),
        'server_receipt_sha256': sha(Path(server_receipt))})
    groups = defaultdict(list)
    for line in INPUTS.read_text(encoding='utf-8').splitlines():
        store = SourceStore(json.loads(line)); groups[policy_hash(store)].append(store)
    samples, replies, failure = defaultdict(list), [], None
    approval = json.loads((DIRECTORY / 'budget_approval.json').read_text(encoding='utf-8'))
    for query in records():
        reply = transport(query['messages'])
        entry = {'policy_sha256': query['policy_sha256'], 'sample_index': query['sample_index'],
            'request_sha256': query['request_sha256'], 'reply': reply}
        try:
            if reply.get('status') != 'OK': raise ValueError(reply.get('reason', 'provider_failed'))
            sample = Compilation.model_validate(decode_model_object(reply['content'])).model_dump()
            samples[query['policy_sha256']].append(sample)
            entry['schema_status'] = 'VALID'
        except (ValueError, TypeError, KeyError) as exc:
            entry.update(schema_status='FAILED', failure_reason=str(exc))
            failure = str(exc)
        replies.append(entry)
        # The raw API record is persisted before testing the batch stop condition.
        write_new(DIRECTORY / ('reply_' + query['policy_sha256'] + '_' + str(query['sample_index']) + '.json'), entry)
        snapshot = transport.snapshot()
        delta_calls = snapshot['actual_api_attempts'] - before['actual_api_attempts']
        delta_tokens = (snapshot['known_provider_tokens'] + snapshot['unknown_usage_upper_bounds']
            - before['known_provider_tokens'] - before['unknown_usage_upper_bounds'])
        if delta_calls > approval['planned_http_attempts'] * 1.2 or delta_tokens > approval['planned_tokens_upper_bound'] * 1.2:
            failure = 'planned_phase_budget_overrun'
        if failure: break
    if failure is None:
        for key, stores in sorted(groups.items()):
            table = assemble(stores, samples[key])
            table.compilation_metadata = {'compiler_freeze_sha256': sha(DIRECTORY / 'frozen.json'),
                'request_model': freeze['model'], 'provider': freeze['provider'], 'reasoning_effort': freeze['reasoning_effort'],
                'max_output_tokens': freeze['max_output_tokens'],
                'served_models': [r['reply'].get('served_model') for r in replies if r['policy_sha256'] == key],
                'sample_request_sha256': [r['request_sha256'] for r in replies if r['policy_sha256'] == key]}
            write_new(ROOT / 'outputs/searh_23/policy_tables' / (key + '.json'), table.model_dump())
    summary = {'status': 'FAILED' if failure else 'COMPILED_NOT_DETECTOR_VALIDATED', 'failure_reason': failure,
        'before': before, 'after': transport.snapshot(), 'completed_replies': len(replies),
        'no_predictions_no_gold': True, 'automatic_retries': 0}
    write_new(DIRECTORY / 'execution_result.json', summary)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--freeze', action='store_true')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--server-receipt', type=Path)
    args = parser.parse_args()
    if args.freeze and args.execute: parser.error('freeze must be committed in a separate step before execute')
    if args.execute:
        if not args.server_receipt: parser.error('--server-receipt is required')
        summary = execute(args.server_receipt)
        print(json.dumps(summary, ensure_ascii=True))
    elif args.freeze:
        print(json.dumps({'status': prepare()['status'], 'api_calls': 0}))
    else:
        print(json.dumps({'status': 'NOT_EXECUTED', 'prepared_requests': len(records()), 'api_calls': 0}))
