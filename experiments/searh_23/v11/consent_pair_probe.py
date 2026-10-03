"""Frozen, label-free consent extraction probe. No production predictor changes.

Phases: inventory, freeze, verify, run, score. Only run may contact a model.
Commit the freeze and its source blobs before run. JSON is requested in the prompt;
the transport deliberately does not use an Ollama cloud response_format schema.
"""
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import random
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
from guardian_truth.parsing import MARKER
from guardian_truth.policy_table.segment import policy_hash
from guardian_truth.policy_table_v11.catalog import normalize_catalog
from guardian_truth.policy_table_v11.transport import Transport
from guardian_truth.source_search.pipeline import decode_model_object
from guardian_truth.source_search.store import SourceStore

INPUTS = ROOT / 'outputs/searh_23/source_search_20261002/comparison_ids_v5/inputs.jsonl'
PREPARATION = ROOT / 'outputs/searh_23/v11/preparation'
PEER = ROOT / 'outputs/searh_23/v11/proposal_review/peer_reproduced_35ce9821.json'
RUN = ROOT / 'outputs/searh_23/v11/consent_pair_probe'
LEDGER = '/workspace/guardian/results/v11-policy-table-20261003'
VERSION = 'consent-pair-probe/1'
SEED = 20261003
REAL_COUNT = 84
EXPLICIT_CONSENT_COUNT = 19
PEER_CONSENT_COUNT = 14
ANNOTATION_STATUS = 'SOURCE_MANUAL_ANNOTATION_NOT_AUTOMATIC_SCOPE_PROOF'
MODELS = [
    {'model': 'gpt-oss:120b', 'family': 'gpt-oss', 'provider': 'ollama', 'reasoning_effort': 'low'},
    {'model': 'gemma4:31b', 'family': 'gemma', 'provider': 'ollama', 'reasoning_effort': None},
]
STOP_STATUSES = {'AUTH_STOP', 'BUDGET_STOP', 'PROVIDER_STOP'}
STATE_ONLY_PEER_IDS = {
    'scalar_secondary_ID_no_longer_blocks_read', 'scalar_other_record_remains_unknown',
    'collection_TARGET_other_parent_leaks',
}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def write(path, value):
    """Atomic checkpoints survive interruption between completed model families."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w', encoding='utf-8', newline='\n') as file:
        json.dump(value, file, ensure_ascii=False, indent=2, allow_nan=False)
        file.write('\n')
        file.flush()
        os.fsync(file.fileno())
    os.replace(temporary, path)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def semantic():
    from guardian_truth.policy_table_v11 import consent_pair
    return consent_pair


def source_row(row):
    """Keep precisely the immutable input fields, with no scores or labels."""
    result = {key: row[key] for key in ('id', 'prompt', 'response')}
    if any(not isinstance(value, str) for value in result.values()):
        raise ValueError('invalid_input_row')
    return result


def make_case(row, target, *, identifier, kind, expected=None, policy=None, role=None):
    row = source_row(row)
    store = SourceStore(row)
    source = store.sources.get(target.get('source_id'))
    if not source or source['kind'] != 'call' or source['role'] != 'assistant':
        raise ValueError('target_not_native_assistant_call:' + identifier)
    events = store.history_events if source['document'] == 'prompt' else store.target_events
    event = events[source['event']]
    if event.name != target.get('tool') or fingerprint(event.value) != fingerprint(target.get('arguments')):
        raise ValueError('target_not_exact_native_call:' + identifier)
    return {'id': identifier, 'case_id': row['id'], 'kind': kind, 'row': row,
            'target': deepcopy(target), 'policy_sha256': policy, 'tool_role': role,
            'source_sha256': store.source_sha256, 'target_source': source,
            'target_arguments_valid': event.json_valid and isinstance(event.value, dict),
            'expected': expected}


def select_real_cases(rows):
    """Copy prepare.witnesses order: sorted policies, input stores, h then t.

    UNKNOWN declared roles are included. Undeclared tools are excluded by the
    original preparation rule, and are counted explicitly in the manifest.
    Malformed calls remain selected, including their original arguments=None.
    """
    groups = defaultdict(list)
    for row in rows:
        row = source_row(row)
        store = SourceStore(row)
        groups[policy_hash(store)].append((row, store))
    cases, excluded, reads = [], [], 0
    for policy, stores in sorted(groups.items()):
        catalog = normalize_catalog([store for _, store in stores])
        for row, store in stores:
            for prefix, events in [('h', store.history_events), ('t', store.target_events)]:
                for index, event in enumerate(events):
                    if event.kind != 'call' or event.role != 'assistant':
                        continue
                    sid = prefix + str(index)
                    if event.name not in catalog['tools']:
                        excluded.append({'case_id': row['id'], 'source_id': sid, 'tool': event.name})
                        continue
                    role = catalog['tools'][event.name]['role']
                    if role == 'READ':
                        reads += 1
                        continue
                    target = {'source_id': sid, 'tool': event.name, 'arguments': event.value}
                    cases.append(make_case(row, target, identifier=row['id'] + '/' + sid,
                                           kind='REAL_LABEL_FREE', policy=policy, role=role))
    if len({case['id'] for case in cases}) != len(cases):
        raise ValueError('duplicate_case_target')
    return cases, {'undeclared_excluded': excluded, 'read_calls_excluded': reads}


def witness_key(case):
    return {'case_id': case['case_id'], 'policy': case['policy_sha256'], 'target': case['target']}


def inventory_data():
    rows = [json.loads(line) for line in INPUTS.read_text(encoding='utf-8').splitlines() if line.strip()]
    cases, exclusions = select_real_cases(rows)
    if len(cases) != REAL_COUNT:
        raise ValueError('real_cohort_count_changed:' + str(len(cases)))
    keys = [witness_key(case) for case in cases]
    prepared = read(PREPARATION / 'witness_inventory.json')
    previous = [{key: row[key] for key in ('case_id', 'policy', 'target')} for row in prepared['calls']]
    if keys != previous:
        raise ValueError('preparation_witness_order_changed')
    sample = random.Random(SEED).sample(cases, min(20, len(cases)))
    review = read(PREPARATION / 'witness_review_20.json')
    reviewed = [{key: row[key] for key in ('case_id', 'policy', 'target')} for row in review['sample']]
    if review.get('seed') != SEED or [witness_key(case) for case in sample] != reviewed:
        raise ValueError('preparation_review_sample_changed')
    return {'cases': cases, 'sample_seed': SEED, 'sample_20': [case['id'] for case in sample],
            'preparation_signature': fingerprint(keys), 'selection':
            'PREPARE_WITNESSES_SORTED_POLICY_INPUT_STORE_HISTORY_THEN_TARGET_NON_READ_DECLARED_ASSISTANT',
            'exclusions': exclusions, 'gold_opened': False, 'api_calls': 0}


def inventory():
    value = inventory_data()
    write(RUN / 'inventory.json', value)
    return {'real_cases': len(value['cases']),
            'malformed_targets': sum(not case['target_arguments_valid'] for case in value['cases']),
            'unknown_role_targets': sum(case['tool_role'] == 'UNKNOWN' for case in value['cases']),
            'by_tool': dict(Counter(case['target']['tool'] for case in value['cases'])),
            'undeclared_excluded': len(value['exclusions']['undeclared_excluded']),
            'sample_seed': SEED, 'sample_20': value['sample_20'],
            'artifact': str(RUN / 'inventory.json'), 'gold_opened': False, 'api_calls': 0}


def synthetic_case(item, *, prefix='synthetic/'):
    row = item.get('row', item.get('fixture'))
    row = {'id': item['id'], **source_row({'id': item['id'], **row})}
    expected = item['expected']
    if isinstance(expected, (tuple, list)):
        if len(expected) != 2:
            raise ValueError('invalid_synthetic_expectation')
        status, value = expected
        expected = ('TRUE' if value else 'FALSE') if status == 'RESOLVED' and type(value) is bool else 'UNRESOLVED'
    if expected not in ('TRUE', 'FALSE', 'UNRESOLVED'):
        raise ValueError('invalid_synthetic_expectation')
    store = SourceStore(row)
    target = item.get('target')
    if target is None:
        targets = [{'source_id': 't' + str(index), 'tool': event.name, 'arguments': event.value}
                   for index, event in enumerate(store.target_events)
                   if event.kind == 'call' and event.role == 'assistant']
        if len(targets) != 1:
            raise ValueError('synthetic_target_required:' + item['id'])
        target = targets[0]
    identifier = item['id'] if item['id'].startswith(prefix) else prefix + item['id']
    case = make_case(row, target, identifier=identifier, kind='SYNTHETIC', expected=expected)
    case['expectation_scope'] = 'ACTION_CONSENT_ONLY_NOT_WHOLE_RESPONSE_LABEL'
    if 'source_qualified_expected' in item:
        if item['source_qualified_expected'] not in ('TRUE', 'FALSE', 'UNRESOLVED'):
            raise ValueError('invalid_source_qualified_expectation')
        case['source_qualified_expected'] = item['source_qualified_expected']
    if 'annotations' in item:
        case['annotations'] = deepcopy(item['annotations'])
    return case


def peer_cases():
    peer = read(PEER)
    selected, excluded = [], []
    for item in peer['synthetic']:
        if item['id'] in STATE_ONLY_PEER_IDS:
            excluded.append({'id': item['id'], 'reason': 'STATE_ONLY_NOT_CONSENT', 'expected': item['expected']})
        else:
            if not isinstance(item.get('expected'), list):
                raise ValueError('unexpected_peer_expectation:' + item['id'])
            case = synthetic_case(item)
            if item['id'] == 'courtesy_ru':
                # Preserve the historical peer expectation while recording the
                # pre-inference audit: this proposal omits operation and amount.
                case['annotations'] = ['parameter_scope_underspecified']
                case['source_qualified_expected'] = 'UNRESOLVED'
            selected.append(case)
    if len(selected) != PEER_CONSENT_COUNT or {row['id'] for row in excluded} != STATE_ONLY_PEER_IDS:
        raise ValueError('peer_fixture_inventory_changed')
    return selected, {'total_peer_replay': len(peer['synthetic']), 'consent_included': len(selected),
                      'state_only_excluded': excluded, 'source': PEER.relative_to(ROOT).as_posix()}


def source_paths():
    # Include transitive parser/store/semantic dependencies and the cohort sources.
    paths = {path.relative_to(ROOT).as_posix() for path in (ROOT / 'src/guardian_truth').rglob('*.py')}
    paths |= {path.relative_to(ROOT).as_posix() for path in (ROOT / 'tests').glob('test_policy_table_v11*.py')}
    paths |= {'experiments/searh_23/v11/consent_pair_probe.py', 'experiments/searh_23/v11/prepare.py',
              INPUTS.relative_to(ROOT).as_posix(), PEER.relative_to(ROOT).as_posix(),
              (PREPARATION / 'witness_inventory.json').relative_to(ROOT).as_posix(),
              (PREPARATION / 'witness_review_20.json').relative_to(ROOT).as_posix()}
    required = {'docs/v11/CONSENT_PAIR_PROTOCOL_2026-10-03.md',
                'experiments/searh_23/v11/consent_pair_extra.py',
                'outputs/searh_23/v11/consent_pair_probe/extra_cases.json',
                'outputs/searh_23/v11/consent_pair_probe/source_review_20_before_api.json'}
    for path in sorted(required):
        if not (ROOT / path).is_file():
            raise ValueError('required_protocol_source_missing:' + path)
    paths |= required
    if 'src/guardian_truth/policy_table_v11/consent_pair.py' not in paths:
        raise ValueError('consent_pair_source_missing')
    return sorted(paths)


def packet_sizes(cases):
    summary = {}
    for kind in ('SYNTHETIC', 'REAL_LABEL_FREE'):
        selected = [case for case in cases if case['kind'] == kind]
        packets, messages, distinct = [], [], set()
        for case in selected:
            if not in_scope(case) or not case['target_arguments_valid']:
                continue
            store = SourceStore(case['row'])
            packet = semantic().packet(store, case['target'])
            request = semantic().request(store, case['target'])
            packets.append(len(json.dumps(packet, ensure_ascii=False, separators=(',', ':')).encode('utf-8')))
            messages.append(len(json.dumps(request, ensure_ascii=False).encode('utf-8')))
            distinct.add(fingerprint(request))
        def distribution(values):
            return {'min': min(values), 'median': statistics.median(values), 'max': max(values)} if values else None
        summary[kind] = {'cases': len(selected), 'request_eligible': len(packets),
                         'unique_messages': len(distinct), 'context_packet_utf8_bytes': distribution(packets),
                         'messages_utf8_bytes': distribution(messages)}
    return summary


def git_blob(path):
    """Hash the Git clean-filter bytes, so CRLF worktrees match committed blobs."""
    result = subprocess.run(['git', 'hash-object', '--path=' + path, '--stdin'], cwd=ROOT,
                            input=(ROOT / path).read_bytes(), capture_output=True, check=True)
    return result.stdout.decode('ascii').strip()


def committed_blob(path):
    try:
        return subprocess.check_output(['git', 'rev-parse', 'HEAD:' + path], cwd=ROOT, stderr=subprocess.PIPE,
                                       text=True).strip()
    except subprocess.CalledProcessError as exc:
        raise ValueError('source_not_committed:' + path) from exc


def in_scope(case):
    return case['kind'] == 'SYNTHETIC' or case.get('explicit_confirmation_scope', {}).get('selected', True)


def annotate_scope(cases, annotations=None):
    if annotations is None:
        annotations = read(RUN / 'source_review_20_before_api.json')['policy_applicability']
    if not isinstance(annotations, list):
        raise ValueError('policy_applicability_must_be_list')
    indexed = {}
    for annotation in annotations:
        policy = annotation['policy_sha256']
        if policy in indexed or annotation['status'] not in (
                'EXPLICIT_USER_CONFIRMATION', 'NO_GLOBAL_EXPLICIT_USER_CONFIRMATION'):
            raise ValueError('policy_applicability_duplicate_or_invalid')
        tools = annotation.get('governed_tools', [])
        if not isinstance(tools, list) or any(not isinstance(tool, str) for tool in tools):
            raise ValueError('policy_governed_tools_invalid')
        if annotation['status'] == 'NO_GLOBAL_EXPLICIT_USER_CONFIRMATION' and tools:
            raise ValueError('nonapplicable_policy_has_governed_tools')
        indexed[policy] = annotation
    annotated = deepcopy(cases)
    for case in annotated:
        policy = case['policy_sha256']
        if policy not in indexed:
            raise ValueError('policy_applicability_incomplete:' + policy)
        annotation = indexed[policy]
        selected = (annotation['status'] == 'EXPLICIT_USER_CONFIRMATION' and
                    case['target']['tool'] in annotation.get('governed_tools', []))
        case['explicit_confirmation_scope'] = {
            'selected': selected, 'annotation_status': ANNOTATION_STATUS,
            'policy_sha256': policy, 'policy_status': annotation['status'],
            'selection_basis': 'POLICY_SHA256_AND_GOVERNED_TOOL_ONLY', 'runtime_use_prohibited': True}
    selected = sum(in_scope(case) for case in annotated)
    if selected != EXPLICIT_CONSENT_COUNT:
        raise ValueError('explicit_consent_cohort_count_changed:' + str(selected))
    return annotated, {'annotation_status': ANNOTATION_STATUS, 'policy_annotations': deepcopy(annotations),
                       'explicit_consent_calls': selected, 'outside_calls': len(cases) - selected,
                       'runtime_use_prohibited': True}


def freeze(extra_cases=None):
    path = RUN / 'freeze.json'
    if path.exists():
        raise ValueError('freeze_already_exists')
    cohort = inventory_data()
    synthetic, peer = peer_cases()
    extras = [synthetic_case(case, prefix='extra/') for case in (extra_cases or [])]
    real, applicability = annotate_scope(cohort['cases'])
    cases = synthetic + extras + real
    if len({case['id'] for case in cases}) != len(cases):
        raise ValueError('duplicate_frozen_case')
    value = {'version': VERSION, 'sources': {path: git_blob(path) for path in source_paths()},
             'cases': cases, 'case_order': [case['id'] for case in cases], 'models': deepcopy(MODELS),
             'max_output_tokens': 8192, 'timeout': 180, 'temperature': 0,
             'model_backend': 'PLAIN_JSON_PROMPT_NO_RESPONSE_FORMAT_SCHEMA',
             'output_contract': 'CONSENT_PAIR_SOURCE_BOUND_JSON/1',
             'ledger': LEDGER, 'limits': {'http': 450, 'tokens': 3000000},
             'retry': {'syntax': 1, 'same_messages': True, 'no_length_retry': True, 'no_status_retry': True},
             'selection': cohort['selection'], 'selection_exclusions': cohort['exclusions'],
             'sample_seed': SEED, 'sample_20': cohort['sample_20'],
             'preparation_signature': cohort['preparation_signature'], 'peer_replay': peer,
             'policy_applicability': applicability,
             'packet_sizes': packet_sizes(cases),
             'expected': {'real': REAL_COUNT, 'explicit_consent_calls': EXPLICIT_CONSENT_COUNT,
                          'peer_consent': PEER_CONSENT_COUNT, 'extra_synthetic': len(extras)},
             'negative_control': {'name': 'M1', 'remove': 'ALL_USER_TEXT_AFTER_FIRST_ASSISTANT_TEXT',
                                  'preserve': 'INITIAL_REQUEST_AND_TARGET_ARGUMENTS',
                                  'mode': 'OFFLINE_READMIT_ORIGINAL_DECODED_RESPONSES', 'expected': 'NEVER_TRUE'},
             'safety_gate': {'name': 'RESOLVED_SYNTHETIC_CONSENSUS_BEFORE_REAL',
                             'expected': 'SOURCE_QUALIFIED_EXPECTED_OR_HISTORICAL_EXPECTED',
                             'failure': 'STOP_REQUIRE_NEW_VERSION_AND_FREEZE',
                             'unknown_aborts': False, 'missing_aborts': False},
             'gold_opened': False, 'decision_status': 'SHADOW_ONLY', 'code_proof': False}
    write(path, value)
    return {'real_cases': REAL_COUNT, 'synthetic_cases': len(synthetic) + len(extras),
            'peer_replay_total': peer['total_peer_replay'], 'main_model_slots': EXPLICIT_CONSENT_COUNT * len(MODELS),
            'real_model_evaluation_slots': REAL_COUNT * len(MODELS),
            'outside_scope_slots_without_http': (REAL_COUNT - EXPLICIT_CONSENT_COUNT) * len(MODELS),
            'synthetic_model_slots': (len(synthetic) + len(extras)) * len(MODELS),
            'malformed_slots_without_http': sum(not case['target_arguments_valid'] for case in cases) * len(MODELS),
            'freeze': str(path), 'status': 'COMMIT_FREEZE_AND_SOURCES_BEFORE_RUN', 'api_calls': 0}


def verify():
    path = RUN / 'freeze.json'
    value = read(path)
    relative = path.relative_to(ROOT).as_posix()
    try:
        sealed = json.loads(subprocess.check_output(['git', 'show', 'HEAD:' + relative], cwd=ROOT,
                                                   stderr=subprocess.PIPE))
    except subprocess.CalledProcessError as exc:
        raise ValueError('freeze_not_committed') from exc
    if value != sealed:
        raise ValueError('freeze_not_committed')
    for source, blob in value['sources'].items():
        if git_blob(source) != blob:
            raise ValueError('frozen_source_changed:' + source)
        if committed_blob(source) != blob:
            raise ValueError('frozen_source_blob_not_committed:' + source)
    if value['version'] != VERSION or value['models'] != MODELS:
        raise ValueError('frozen_config_changed')
    if [case['id'] for case in value['cases']] != value['case_order']:
        raise ValueError('frozen_case_order_changed')
    seen_real = False
    for case in value['cases']:
        seen_real |= case['kind'] == 'REAL_LABEL_FREE'
        if seen_real and case['kind'] == 'SYNTHETIC':
            raise ValueError('frozen_synthetic_cases_must_precede_real')
    if len([case for case in value['cases'] if case['kind'] == 'REAL_LABEL_FREE']) != REAL_COUNT:
        raise ValueError('frozen_real_count_changed')
    real = [case for case in value['cases'] if case['kind'] == 'REAL_LABEL_FREE']
    if any('explicit_confirmation_scope' not in case for case in real):
        raise ValueError('frozen_scope_annotation_missing')
    if sum(in_scope(case) for case in real) != EXPLICIT_CONSENT_COUNT:
        raise ValueError('frozen_explicit_consent_count_changed')
    for case in value['cases']:
        rebuilt = make_case(case['row'], case['target'], identifier=case['id'], kind=case['kind'])
        for field in ('source_sha256', 'target_source', 'target_arguments_valid'):
            if rebuilt[field] != case[field]:
                raise ValueError('frozen_case_source_changed:' + case['id'])
    return value


def request_id(messages, model, frozen):
    # Case IDs and hidden target arguments are deliberately absent from this key.
    return fingerprint({'messages': messages, 'model_config': model, 'version': frozen['version'],
                        'output_contract': frozen['output_contract'],
                        'semantic_source': frozen['sources'].get('src/guardian_truth/policy_table_v11/consent_pair.py'),
                        'max_output_tokens': frozen['max_output_tokens'], 'timeout': frozen['timeout'],
                        'temperature': frozen['temperature'], 'backend': frozen['model_backend'],
                        'retry': frozen['retry']})


def transport(model, frozen):
    return Transport(frozen['ledger'], model['provider'], model['model'],
                     reasoning_effort=model['reasoning_effort'], temperature=frozen['temperature'],
                     max_output_tokens=frozen['max_output_tokens'], timeout=frozen['timeout'],
                     max_calls=frozen['limits']['http'], max_tokens=frozen['limits']['tokens'])


def stop_reason(reply):
    status = reply.get('status')
    if status in STOP_STATUSES:
        return status
    if reply.get('http_status') in (401, 403):
        return 'AUTH_STOP'
    if reply.get('http_status') in (402, 429):
        return 'PROVIDER_STOP'
    if status == 'UNAVAILABLE' and 'attempt_id' not in reply:
        return 'UNAVAILABLE_WITHOUT_ATTEMPT'
    return None


def budget_stop(snapshot, model, frozen):
    if snapshot.get('auth_stop'):
        return 'AUTH_STOP'
    if 'breaker_' + model['provider'] in snapshot.get('provider_breakers', []):
        return 'PROVIDER_STOP'
    if (snapshot['http_attempts'] >= frozen['limits']['http'] or
            snapshot['known_tokens'] + snapshot['unknown_upper_bound'] >= frozen['limits']['tokens']):
        return 'BUDGET_STOP'
    return None


def finished_by_length(reply):
    choices = reply.get('provider_response', {}).get('choices') or [{}]
    return choices[0].get('finish_reason') in ('length', 'max_tokens')


def call(messages, model, frozen):
    uid = request_id(messages, model, frozen)
    path = RUN / 'replies' / (uid + '.json')
    saved = read(path) if path.exists() else None
    if saved and saved.get('complete'):
        return {**saved, 'reused': True}
    record = saved or {'request_sha256': uid, 'model': model, 'messages': messages,
                       'reply': None, 'retry': None, 'decoded': None, 'complete': False}
    if record['request_sha256'] != uid or record['messages'] != messages or record['model'] != model:
        raise ValueError('request_cache_mismatch')
    client = transport(model, frozen)

    def obtain(slot, sample):
        previous = record.get(slot)
        # A stop without an HTTP attempt is pending, and may be resumed safely.
        if previous is None or stop_reason(previous) and 'attempt_id' not in previous:
            record[slot] = client(messages, fresh_sample=sample)
            write(path, record)  # Raw persists before any decoding or admission.
        return record[slot]

    reply = obtain('reply', uid)
    record['outcome'] = reply['status']
    record['blocked'] = stop_reason(reply)
    if record['blocked'] and 'attempt_id' not in reply:
        write(path, record)
        return record
    if reply['status'] == 'OK':
        if finished_by_length(reply):
            record['outcome'] = 'LENGTH'
        else:
            try:
                decoded = decode_model_object(reply.get('content'))
                fingerprint(decoded)  # Reject non-finite, non-JSON values.
                record['decoded'] = decoded
                record['syntax_valid'] = True
            except (ValueError, TypeError, RecursionError):
                retry = obtain('retry', uid + '/syntax_retry')
                record['outcome'] = retry['status']
                record['blocked'] = stop_reason(retry)
                if record['blocked'] and 'attempt_id' not in retry:
                    write(path, record)
                    return record
                if retry['status'] == 'OK':
                    if finished_by_length(retry):
                        record['outcome'] = 'LENGTH'
                    else:
                        try:
                            decoded = decode_model_object(retry.get('content'))
                            fingerprint(decoded)
                            record['decoded'] = decoded
                            record['syntax_valid'] = True
                        except (ValueError, TypeError, RecursionError):
                            pass
                if not record.get('syntax_valid') and record['outcome'] == 'OK':
                    record['outcome'] = 'INVALID_JSON'
    record['complete'] = True
    write(path, record)
    return record


def raw_record(record):
    return read(RUN / record['raw_path']) if record.get('raw_path') else None


def model_record(raw, model, store, target):
    checked = semantic().admit(raw['decoded'], store, target)
    return {'family': model['family'], 'model': model, 'outcome': raw['outcome'],
            'request_sha256': raw['request_sha256'], 'raw_path': 'replies/' + raw['request_sha256'] + '.json',
            'reused': raw.get('reused', False), 'admission': checked,
            'verdict': semantic().verdict(checked, store, target), 'complete': True}


def malformed_record(model):
    return {'family': model['family'], 'model': model, 'outcome': 'NOT_CALLED_MALFORMED_TARGET',
            'request_sha256': None, 'raw_path': None, 'complete': True,
            'admission': {'valid': False, 'reason': 'target_arguments_invalid', 'code_proof': False},
            'verdict': {'value': 'UNRESOLVED', 'reason': 'target_arguments_invalid', 'code_proof': False}}


def outside_scope_record(model):
    reason = 'outside_source_annotated_explicit_confirmation_scope'
    return {'family': model['family'], 'model': model,
            'outcome': 'NOT_CALLED_OUTSIDE_EXPLICIT_CONFIRMATION_SCOPE',
            'request_sha256': None, 'raw_path': None, 'complete': True,
            'admission': {'valid': False, 'reason': reason, 'code_proof': False},
            'verdict': {'value': 'UNRESOLVED', 'reason': reason, 'code_proof': False,
                        'scope': 'NOT_APPLICABLE_TO_THIS_RESEARCH_PROBE', 'annotation_status': ANNOTATION_STATUS}}


def ordered_rows(rows, frozen):
    return [rows[case['id']] for case in frozen['cases'] if case['id'] in rows]


def checkpoint(progress, rows, frozen, client):
    progress['rows'] = ordered_rows(rows, frozen)
    progress['budget_after'] = client.snapshot()
    progress['complete'] = all(case['id'] in rows and rows[case['id']].get('complete') for case in frozen['cases'])
    progress['pending_case_ids'] = [case['id'] for case in frozen['cases']
                                    if case['id'] not in rows or not rows[case['id']].get('complete')]
    write(RUN / 'result.json', progress)


def safety_gate(frozen, rows):
    failures, missing, unresolved = [], [], []
    for case in frozen['cases']:
        if case['kind'] != 'SYNTHETIC':
            continue
        row = rows.get(case['id'])
        if not row or not row.get('complete') or not row.get('consensus'):
            missing.append(case['id'])
            continue
        actual = row['consensus']['value']
        expected = case.get('source_qualified_expected', case['expected'])
        if actual == 'UNRESOLVED':
            unresolved.append(case['id'])
        elif actual != expected:
            failures.append({'id': case['id'], 'expected': expected, 'actual': actual,
                             'historical_expected': case['expected']})
    return {'status': 'FAIL' if failures else 'PASS', 'failures': failures,
            'unresolved_case_ids': unresolved, 'missing_case_ids': missing,
            'requires_new_version_and_freeze': bool(failures)}


def run_probe():
    frozen = verify()
    client = transport(frozen['models'][0], frozen)
    path = RUN / 'result.json'
    progress = read(path) if path.exists() else {
        'version': VERSION, 'freeze_sha256': fingerprint(frozen), 'rows': [],
        'budget_before': client.snapshot(), 'sessions': [], 'gold_opened': False,
        'decision_status': 'SHADOW_ONLY', 'code_proof': False,
    }
    if progress.get('freeze_sha256') != fingerprint(frozen):
        raise ValueError('result_freeze_mismatch')
    rows = {row['id']: row for row in progress['rows']}
    if len(rows) != len(progress['rows']) or set(rows) - set(frozen['case_order']):
        raise ValueError('result_case_inventory_mismatch')
    session = {'before': client.snapshot(), 'after': None, 'stop_reason': None}
    progress['sessions'].append(session)
    progress['stop_reason'] = None
    if progress.get('safety_gate', {}).get('status') == 'FAIL':
        progress['stop_reason'] = 'SYNTHETIC_SAFETY_GATE'
        session.update({'after': client.snapshot(), 'stop_reason': progress['stop_reason']})
        checkpoint(progress, rows, frozen, client)
        return score()
    for case in frozen['cases']:
        if case['kind'] == 'REAL_LABEL_FREE':
            progress['safety_gate'] = safety_gate(frozen, rows)
            if progress['safety_gate']['status'] == 'FAIL':
                progress['stop_reason'] = 'SYNTHETIC_SAFETY_GATE'
                break
        if rows.get(case['id'], {}).get('complete'):
            continue
        row = rows.setdefault(case['id'], {'id': case['id'], 'kind': case['kind'],
            'case_id': case['case_id'], 'tool': case['target']['tool'], 'expected': case['expected'],
            'models': [], 'consensus': None, 'complete': False})
        store, target = SourceStore(case['row']), case['target']
        if not in_scope(case):
            row['models'] = [outside_scope_record(model) for model in frozen['models']]
        elif not case['target_arguments_valid']:
            row['models'] = [malformed_record(model) for model in frozen['models']]
        else:
            messages = semantic().request(store, target)
            for model in frozen['models']:
                if any(record['family'] == model['family'] and record.get('complete') for record in row['models']):
                    continue
                uid = request_id(messages, model, frozen)
                cached = RUN / 'replies' / (uid + '.json')
                complete_cache = cached.exists() and read(cached).get('complete')
                stopped = None if complete_cache else budget_stop(client.snapshot(), model, frozen)
                if stopped:
                    row['blocked_model'] = {'family': model['family'], 'reason': stopped}
                    progress['stop_reason'] = stopped
                    break
                raw = call(messages, model, frozen)
                if not raw.get('complete'):
                    row['blocked_model'] = {'family': model['family'], 'reason': raw['blocked'],
                                            'raw_path': 'replies/' + uid + '.json'}
                    progress['stop_reason'] = raw['blocked']
                    checkpoint(progress, rows, frozen, client)
                    break
                row['models'].append(model_record(raw, model, store, target))
                row.pop('blocked_model', None)
                checkpoint(progress, rows, frozen, client)
                if raw.get('blocked'):
                    progress['stop_reason'] = raw['blocked']
                    break
        row['complete'] = len(row['models']) == len(frozen['models'])
        if row['complete']:
            row['consensus'] = semantic().agreement(row['models'])
            row['consensus']['reason'] = ('model_source_semantics_agree' if row['consensus']['agrees']
                                          else 'model_semantics_disagree_or_invalid')
            row['consensus']['model_reasons'] = [record['verdict']['reason'] for record in row['models']]
            if not in_scope(case) or not case['target_arguments_valid']:
                row['consensus']['reason'] = row['models'][0]['verdict']['reason']
            row['scope_annotation'] = case.get('explicit_confirmation_scope')
        checkpoint(progress, rows, frozen, client)
        print(json.dumps({'id': case['id'], 'complete': row['complete'],
                          'values': [record['verdict']['value'] for record in row['models']],
                          'stop_reason': progress['stop_reason'], 'budget': progress['budget_after']}), flush=True)
        if progress['stop_reason']:
            break
    session.update({'after': client.snapshot(), 'stop_reason': progress['stop_reason']})
    if 'safety_gate' not in progress and not progress['stop_reason']:
        progress['safety_gate'] = safety_gate(frozen, rows)
    checkpoint(progress, rows, frozen, client)
    return score()


def m1_mutant(case):
    """Delete approval user blocks and rebuild offsets; native calls stay intact."""
    store = SourceStore(case['row'])
    removed, spans = [], defaultdict(list)
    seen_assistant = False
    for prefix, events in [('h', store.history_events), ('t', store.target_events)]:
        for index, event in enumerate(events):
            if event.kind == 'text' and event.role == 'assistant':
                seen_assistant = True
            if not seen_assistant or event.kind != 'text' or event.role != 'user':
                continue
            raw = store.raw[event.source.document]
            preceding = [marker for marker in MARKER.finditer(raw)
                         if marker.end() <= event.source.start]
            marker = preceding[-1] if preceding else None
            if marker is None or not marker['header'] or marker['header'].split()[0] != 'USER':
                raise ValueError('user_block_marker_missing')
            spans[event.source.document].append((marker.start(), event.source.end))
            removed.append(prefix + str(index))
    row = dict(case['row'])
    for document, cuts in spans.items():
        text = row[document]
        for start, end in sorted(cuts, reverse=True):
            text = text[:start] + text[end:]
        row[document] = text
    mutant = SourceStore(row)
    original_source = store.sources[case['target']['source_id']]
    old_events = store.history_events if original_source['document'] == 'prompt' else store.target_events
    ordinal = sum(event.kind == 'call' for event in old_events[:original_source['event']])
    new_events = mutant.history_events if original_source['document'] == 'prompt' else mutant.target_events
    calls = [(index, event) for index, event in enumerate(new_events) if event.kind == 'call']
    index, event = calls[ordinal]
    prefix = 'h' if original_source['document'] == 'prompt' else 't'
    target = {**case['target'], 'source_id': prefix + str(index)}
    if event.role != 'assistant' or event.name != target['tool'] or fingerprint(event.value) != fingerprint(target['arguments']):
        raise ValueError('M1_target_changed')
    return mutant, target, removed


def negative_control(frozen, rows):
    detailed = []
    for case in frozen['cases']:
        row = rows.get(case['id'])
        if not row or not row['models']:
            continue
        mutant, target, removed = m1_mutant(case)
        models = []
        for original in row['models']:
            raw = raw_record(original)
            if raw is None:
                continue
            admitted = semantic().admit(raw.get('decoded'), mutant, target)
            models.append({'family': original['family'], 'request_sha256': original['request_sha256'],
                           'admission': admitted, 'verdict': semantic().verdict(admitted, mutant, target)})
        if not models:
            continue
        detailed.append({'id': case['id'], 'kind': case['kind'], 'removed_user_source_ids': removed,
                         'mutant_source_sha256': mutant.source_sha256, 'target': target, 'models': models,
                         'consensus': semantic().agreement(models) if len(models) == len(frozen['models']) else None})
    values = Counter(model['verdict']['value'] for row in detailed for model in row['models'])
    failures = Counter(model['admission'].get('reason', 'invalid') for row in detailed
                       for model in row['models'] if not model['admission']['valid'])
    report = {'name': 'M1', 'mode': 'OFFLINE_READMIT_ORIGINAL_DECODED_RESPONSES', 'api_calls': 0,
              'cases': len(detailed), 'model_results': sum(values.values()), 'TRUE': values['TRUE'],
              'FALSE': values['FALSE'], 'UNKNOWN': values['UNRESOLVED'], 'never_true': values['TRUE'] == 0,
              'admission_failures': sum(failures.values()), 'admission_failure_reasons': dict(failures),
              'deleted_user_events': sum(len(row['removed_user_source_ids']) for row in detailed),
              'fresh_model_inference_measured': False, 'claim_scope': 'CODE_CHECK_INVARIANT_ONLY',
              'gold_opened': False, 'code_proof': False}
    write(RUN / 'm1_readmission.json', {'summary': report, 'rows': detailed})
    return report


def counts(records):
    values = Counter(record['value'] for record in records)
    return {'TRUE': values['TRUE'], 'FALSE': values['FALSE'], 'UNKNOWN': values['UNRESOLVED'],
            'reasons': dict(Counter(record.get('reason', 'unspecified') for record in records)),
            'FALSE_by_scope': dict(Counter(record.get('scope', 'UNSPECIFIED')
                                          for record in records if record['value'] == 'FALSE'))}


def synthetic_metrics(pairs, expected, *, expectation_field='expected'):
    completed = len(pairs)
    def want(case):
        return case.get(expectation_field, case['expected'])
    correct = sum(want(case) == verdict['value'] for case, verdict in pairs)
    return {'expected': expected, 'completed': completed, 'missing': expected - completed,
            'correct': correct, 'accuracy': correct / completed if completed else None,
            'expectation_field': expectation_field,
            'wrong_TRUE': sum(verdict['value'] == 'TRUE' and want(case) != 'TRUE' for case, verdict in pairs),
            'wrong_FALSE': sum(verdict['value'] == 'FALSE' and want(case) != 'FALSE' for case, verdict in pairs),
            **counts([verdict for _, verdict in pairs])}


def scope_metrics(real, pairs):
    result = {'annotation_status': ANNOTATION_STATUS, 'runtime_use_prohibited': True}
    for selected, name in [(True, 'explicit_confirmation'), (False, 'outside_confirmation_scope')]:
        cohort = [case for case in real if bool(in_scope(case)) == selected]
        values = [verdict for case, verdict in pairs if bool(in_scope(case)) == selected]
        result[name] = {'expected': len(cohort), 'completed': len(values), 'missing': len(cohort) - len(values),
                        'model_eligible': sum(case['target_arguments_valid'] and selected for case in cohort),
                        **counts(values)}
    return result


def own_cost(records):
    attempts = {}
    for record in records:
        raw = raw_record(record)
        for reply in [raw.get('reply'), raw.get('retry')] if raw else []:
            if reply and 'attempt_id' in reply:
                key = (reply.get('provider', record['model']['provider']), reply['attempt_id'])
                attempts[key] = reply
    return {'http_attempts': len(attempts),
            'known_tokens': sum(reply.get('known_tokens', 0) for reply in attempts.values()),
            'unknown_upper_bound': sum(reply.get('unknown_upper_bound', 0) for reply in attempts.values()),
            'seconds': sum(reply.get('seconds', 0) for reply in attempts.values())}


def score():
    frozen = verify()
    result = read(RUN / 'result.json')
    if result.get('freeze_sha256') != fingerprint(frozen):
        raise ValueError('result_freeze_mismatch')
    rows = {row['id']: row for row in result['rows']}
    if not rows and (RUN / 'score.json').exists():
        raise ValueError('empty_result_would_overwrite_report')
    real = [case for case in frozen['cases'] if case['kind'] == 'REAL_LABEL_FREE']
    synthetic = [case for case in frozen['cases'] if case['kind'] == 'SYNTHETIC']
    families = []
    for model in frozen['models']:
        pairs = [(case, record) for case in frozen['cases'] for record in rows.get(case['id'], {}).get('models', [])
                 if record['family'] == model['family'] and record.get('complete')]
        own_real = [(case, record) for case, record in pairs if case['kind'] == 'REAL_LABEL_FREE']
        own_synthetic = [(case, record['verdict']) for case, record in pairs if case['kind'] == 'SYNTHETIC']
        by_tool = []
        for tool in sorted({case['target']['tool'] for case in real}):
            selected = [record['verdict'] for case, record in own_real if case['target']['tool'] == tool]
            expected = sum(case['target']['tool'] == tool for case in real)
            by_tool.append({'tool': tool, 'expected': expected, 'completed': len(selected),
                            'explicit_scope_expected': sum(in_scope(case) and case['target']['tool'] == tool for case in real),
                            'missing': expected - len(selected), **counts(selected)})
        families.append({'model': model, 'real': {'expected': len(real), 'completed': len(own_real),
            'missing': len(real) - len(own_real), **counts([record['verdict'] for _, record in own_real]),
            'strata': scope_metrics(real, [(case, record['verdict']) for case, record in own_real]),
            'by_tool': by_tool}, 'synthetic': synthetic_metrics(own_synthetic, len(synthetic)),
            'source_qualified_synthetic': synthetic_metrics(own_synthetic, len(synthetic),
                                                            expectation_field='source_qualified_expected'),
            'outcomes': dict(Counter(record['outcome'] for _, record in pairs)),
            'admission_valid': sum(record['admission']['valid'] for _, record in pairs),
            'unique_requests': len({record['request_sha256'] for _, record in pairs if record['request_sha256']}),
            'cost': own_cost([record for _, record in pairs])})
    agreed = [(case, rows[case['id']]['consensus']) for case in frozen['cases']
              if case['id'] in rows and rows[case['id']].get('complete') and rows[case['id']].get('consensus')]
    agreed_real = [(case, verdict) for case, verdict in agreed if case['kind'] == 'REAL_LABEL_FREE']
    consensus_tools = []
    for tool in sorted({case['target']['tool'] for case in real}):
        selected = [verdict for case, verdict in agreed_real if case['target']['tool'] == tool]
        expected = sum(case['target']['tool'] == tool for case in real)
        consensus_tools.append({'tool': tool, 'expected': expected, 'completed': len(selected),
                                'explicit_scope_expected': sum(in_scope(case) and case['target']['tool'] == tool for case in real),
                                'missing': expected - len(selected), **counts(selected)})
    all_records = [record for row in rows.values() for record in row['models']]
    before, after = result['budget_before'], result['budget_after']
    report = {'version': VERSION, 'complete': result['complete'], 'stop_reason': result.get('stop_reason'),
              'safety_gate': result.get('safety_gate', {'status': 'NOT_REACHED'}),
              'packet_sizes': frozen.get('packet_sizes'),
              'pending_case_ids': result['pending_case_ids'], 'families': families,
              'consensus': {'real': {'expected': len(real), 'completed': len(agreed_real),
                  'missing': len(real) - len(agreed_real), **counts([verdict for _, verdict in agreed_real]),
                  'strata': scope_metrics(real, agreed_real),
                  'by_tool': consensus_tools},
                  'synthetic': synthetic_metrics([(case, verdict) for case, verdict in agreed
                                                  if case['kind'] == 'SYNTHETIC'], len(synthetic)),
                  'source_qualified_synthetic': synthetic_metrics([(case, verdict) for case, verdict in agreed
                      if case['kind'] == 'SYNTHETIC'], len(synthetic), expectation_field='source_qualified_expected'),
                  'agrees': sum(verdict.get('agrees', False) for _, verdict in agreed)},
              'peer_replay': frozen['peer_replay'], 'policy_applicability': frozen.get('policy_applicability'),
              'M1': negative_control(frozen, rows),
              'cost': {'own_unique_attempts': own_cost(all_records), 'global_before': before, 'global_after': after,
                       'global_delta': {key: after[key] - before[key]
                                        for key in ('http_attempts', 'known_tokens', 'unknown_upper_bound')},
                       'sessions': result['sessions']},
              'artifacts': {'freeze': str(RUN / 'freeze.json'), 'progress': str(RUN / 'result.json'),
                            'fullresult_raw': str(RUN / 'fullresult.raw.json'), 'replies': str(RUN / 'replies'),
                            'M1': str(RUN / 'm1_readmission.json'), 'global_ledger': frozen['ledger']},
              'gold_opened': False, 'whole_detector_improvement_measured': False,
              'decision_status': 'SHADOW_ONLY', 'code_proof': False}
    # Preserve full original raw replies as well as their stable on-disk references.
    receipts = {record['request_sha256']: raw_record(record) for record in all_records if record['raw_path']}
    for row in rows.values():
        pending = row.get('blocked_model', {}).get('raw_path')
        if pending:
            raw = read(RUN / pending)
            receipts[raw['request_sha256']] = raw
    write(RUN / 'fullresult.raw.json', {**result, 'raw_records': receipts})
    write(RUN / 'score.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('inventory', 'freeze', 'verify', 'run', 'score'))
    parser.add_argument('--synthetic-json', type=Path, help='Additional fixtures, used only before freeze.')
    args = parser.parse_args()
    if args.synthetic_json and args.phase != 'freeze':
        parser.error('--synthetic-json is only accepted by freeze')
    if args.phase == 'freeze':
        result = freeze(read(args.synthetic_json) if args.synthetic_json else None)
    elif args.phase == 'verify':
        value = verify()
        result = {'verified': True, 'cases': len(value['cases']), 'sources': len(value['sources']), 'api_calls': 0}
    else:
        result = {'inventory': inventory, 'run': run_probe, 'score': score}[args.phase]()
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
