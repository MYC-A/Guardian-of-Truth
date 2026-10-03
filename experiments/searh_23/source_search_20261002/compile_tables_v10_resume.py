"""Resume the preserved compiler batch with one lossless wire-format repair.

Only an exact {kind: PATH, path: string} wrapper on Condition.lhs is unwrapped.
Paths, operators, literals, clauses, modalities and the schema are unchanged.
No invalid response is re-asked; the parent API ledger and raw replies remain.
"""
import argparse
from collections import defaultdict
from copy import deepcopy
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
from guardian_truth.source_search.pipeline import decode_model_object
from guardian_truth.source_search.store import SourceStore
from compile_tables_v10 import sha, write_new, records, INPUTS

PARENT = ROOT / 'outputs/searh_23/v10/compiler_preparation'
DIRECTORY = ROOT / 'outputs/searh_23/v10/compiler_resume_01'


def parse_wire(value):
    result = deepcopy(value)
    repairs = []
    if isinstance(result, dict) and isinstance(result.get('rules'), list):
        for ri, rule in enumerate(result['rules']):
            if not isinstance(rule, dict): continue
            groups = [rule.get('conditions', [])] + rule.get('exceptions', []) if isinstance(rule.get('exceptions', []), list) else []
            for gi, group in enumerate(groups):
                if not isinstance(group, list): continue
                for ci, condition in enumerate(group):
                    if not isinstance(condition, dict): continue
                    lhs = condition.get('lhs')
                    if (isinstance(lhs, dict) and set(lhs) == {'kind', 'path'}
                            and lhs['kind'] == 'PATH' and isinstance(lhs['path'], str)):
                        condition['lhs'] = lhs['path']
                        repairs.append({'rule_index': ri, 'group_index': gi, 'condition_index': ci,
                            'operation': 'UNWRAP_EXACT_PATH_WRAPPER', 'before': lhs, 'after': lhs['path']})
    return Compilation.model_validate(result).model_dump(), repairs


def previous():
    frozen = json.loads((PARENT / 'frozen.json').read_text(encoding='utf-8'))
    status = json.loads((PARENT / 'execution_result.json').read_text(encoding='utf-8'))
    if status['status'] != 'FAILED': raise ValueError('resume requires the retained technical failure')
    entries = {}
    for path in sorted(PARENT.glob('reply_*.json')):
        entry = json.loads(path.read_text(encoding='utf-8'))
        if entry['reply'].get('status') != 'OK': raise ValueError('transport failure cannot be repaired by a format adapter')
        sample, repairs = parse_wire(decode_model_object(entry['reply']['content']))
        key = (entry['policy_sha256'], entry['sample_index'])
        if key in entries: raise ValueError('duplicate parent sample')
        entries[key] = {'entry': entry, 'sample': sample, 'repairs': repairs, 'source_file': path.relative_to(ROOT).as_posix()}
    if len(entries) != status['completed_replies']: raise ValueError('parent replies are incomplete')
    return frozen, status, entries


def prepare():
    parent, status, entries = previous()
    for relative, expected in parent['source_sha256'].items():
        if sha(ROOT / relative) != expected: raise ValueError('parent source changed: ' + relative)
    remaining = [q for q in records() if (q['policy_sha256'], q['sample_index']) not in entries]
    source_files = list(parent['source_sha256']) + [Path(__file__).relative_to(ROOT).as_posix()]
    source_files += [p.relative_to(ROOT).as_posix() for p in PARENT.glob('reply_*.json')]
    source_files += [(PARENT / name).relative_to(ROOT).as_posix() for name in ('frozen.json', 'budget_approval.json', 'execution_result.json')]
    approval = {'phase': 'V10_COMPILER_RESUME_LOSSLESS_FORMAT_ONLY', 'planned_http_attempts': len(remaining),
        'planned_tokens_upper_bound': sum(q['request_utf8_bytes'] + 8192 + 1024 for q in remaining),
        'phase_overrun_multiplier': 1.2, 'whole_v10_limits': {'http_attempts': 200, 'tokens_including_unknown_bounds': 1500000},
        'parent_charges': status['after'], 'same_persistent_api_ledger': parent['api_ledger_dir'],
        'automatic_retries': 0, 'new_prompts': False, 'gold_opened': False}
    write_new(DIRECTORY / 'budget_approval.json', approval)
    freeze = {'status': 'FROZEN_COMPILER_RESUME_NOT_FINAL_DETECTOR', 'created_at': datetime.now(timezone.utc).isoformat(),
        'source_sha256': {name: sha(ROOT / name) for name in sorted(set(source_files))},
        'budget_approval_sha256': sha(DIRECTORY / 'budget_approval.json'),
        'api_ledger_dir': parent['api_ledger_dir'], 'model': parent['model'], 'provider': parent['provider'],
        'reasoning_effort': parent['reasoning_effort'], 'max_output_tokens': parent['max_output_tokens'],
        'original_requests_unmodified': True, 'retained_samples': len(entries), 'new_api_requests': len(remaining),
        'format_repairs': {value['source_file']: value['repairs'] for value in entries.values()},
        'public46_status': 'BURNED_DEVELOPMENT_DATA', 'gold_opened_by_compiler': False}
    write_new(DIRECTORY / 'frozen.json', freeze)
    return freeze


def verify():
    path = DIRECTORY / 'frozen.json'; frozen = json.loads(path.read_text(encoding='utf-8'))
    for name, expected in frozen['source_sha256'].items():
        if sha(ROOT / name) != expected: raise ValueError('resume source changed: ' + name)
    if sha(DIRECTORY / 'budget_approval.json') != frozen['budget_approval_sha256']: raise ValueError('resume budget changed')
    archived = subprocess.check_output(['git', 'show', 'HEAD:' + path.relative_to(ROOT).as_posix()], cwd=ROOT)
    if archived != path.read_bytes(): raise ValueError('resume freeze must be committed before API')
    return frozen


def execute(receipt_path):
    frozen = verify(); _, parent_status, retained = previous()
    receipt = json.loads(Path(receipt_path).read_text(encoding='utf-8'))
    for name in ('operating_guide_read_fully', 'python_environment_verified', 'credentials_presence_verified', 'prior_expenses_preserved'):
        if receipt.get(name) is not True: raise ValueError('missing server prerequisite: ' + name)
    from guardian_truth.source_search.transport import ModelTransport
    transport = ModelTransport(Path(frozen['api_ledger_dir']), max_calls=200, max_tokens=1500000,
        max_output_tokens=frozen['max_output_tokens'], timeout=300, provider=frozen['provider'], model=frozen['model'],
        reasoning_effort=frozen['reasoning_effort'], json_mode=False)
    before = transport.snapshot()
    for name in ('actual_api_attempts', 'known_provider_tokens', 'unknown_usage_upper_bounds', 'pending_reservations'):
        if before[name] != parent_status['after'][name]: raise ValueError('parent ledger changed: ' + name)
    write_new(DIRECTORY / 'execution_started.json', {'before': before, 'freeze_sha256': sha(DIRECTORY / 'frozen.json')})
    samples, replies, failure = defaultdict(list), [], None
    approval = json.loads((DIRECTORY / 'budget_approval.json').read_text(encoding='utf-8'))
    for query in records():
        key = (query['policy_sha256'], query['sample_index'])
        if key in retained:
            item = retained[key]; sample, repairs = item['sample'], item['repairs']
            entry = {**item['entry'], 'retained_from': item['source_file'], 'lossless_format_repairs': repairs, 'schema_status': 'VALID_AFTER_LOSSLESS_REPAIR' if repairs else 'VALID'}
        else:
            reply = transport(query['messages'])
            entry = {'policy_sha256': key[0], 'sample_index': key[1], 'request_sha256': query['request_sha256'], 'reply': reply}
            try:
                if reply.get('status') != 'OK': raise ValueError(reply.get('reason', 'provider_failed'))
                sample, repairs = parse_wire(decode_model_object(reply['content']))
                entry.update(schema_status='VALID_AFTER_LOSSLESS_REPAIR' if repairs else 'VALID', lossless_format_repairs=repairs)
            except (ValueError, TypeError, KeyError) as exc:
                failure = str(exc); entry.update(schema_status='FAILED', failure_reason=failure)
        replies.append(entry)
        write_new(DIRECTORY / ('reply_' + key[0] + '_' + str(key[1]) + '.json'), entry)
        if not failure: samples[key[0]].append(sample)
        snap = transport.snapshot()
        delta_tokens = snap['known_provider_tokens'] + snap['unknown_usage_upper_bounds'] - before['known_provider_tokens'] - before['unknown_usage_upper_bounds']
        if (snap['actual_api_attempts'] - before['actual_api_attempts'] > approval['planned_http_attempts'] * 1.2
                or delta_tokens > approval['planned_tokens_upper_bound'] * 1.2): failure = 'planned_phase_budget_overrun'
        if failure: break
    if not failure:
        groups = defaultdict(list)
        for line in INPUTS.read_text(encoding='utf-8').splitlines():
            store = SourceStore(json.loads(line)); groups[policy_hash(store)].append(store)
        for key, stores in sorted(groups.items()):
            table = assemble(stores, samples[key])
            table.compilation_metadata = {'compiler_freeze_sha256': sha(DIRECTORY / 'frozen.json'),
                'parent_freeze_sha256': sha(PARENT / 'frozen.json'), 'request_model': frozen['model'],
                'provider': frozen['provider'], 'reasoning_effort': frozen['reasoning_effort'],
                'max_output_tokens': frozen['max_output_tokens'], 'original_requests_unmodified': True,
                'served_models': [r['reply'].get('served_model') for r in replies if r['policy_sha256'] == key],
                'lossless_format_repairs': sum(len(r.get('lossless_format_repairs', [])) for r in replies if r['policy_sha256'] == key),
                'sample_request_sha256': [r['request_sha256'] for r in replies if r['policy_sha256'] == key]}
            write_new(ROOT / 'outputs/searh_23/policy_tables' / (key + '.json'), table.model_dump())
    summary = {'status': 'FAILED' if failure else 'COMPILED_NOT_DETECTOR_VALIDATED', 'failure_reason': failure,
        'before': before, 'after': transport.snapshot(), 'completed_replies': len(replies), 'retained_samples': len(retained),
        'new_prompts': False, 'automatic_retries': 0, 'no_predictions_no_gold': True}
    write_new(DIRECTORY / 'execution_result.json', summary)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--freeze', action='store_true'); group.add_argument('--execute', action='store_true')
    parser.add_argument('--server-receipt', type=Path); args = parser.parse_args()
    if args.execute and not args.server_receipt: parser.error('--server-receipt required')
    print(json.dumps(execute(args.server_receipt) if args.execute else prepare(), ensure_ascii=True))
