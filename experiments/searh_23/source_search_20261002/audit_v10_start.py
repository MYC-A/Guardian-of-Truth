"""Read-only V10 starting-state audit. No transport, inference, or gate changes.

Uses the committed V5 archive and historical labels already opened for V5.
The outputs describe old proposals, not new predictions or an A1 replay.
"""
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
import re
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
from guardian_truth.parsing import parse_catalog
from guardian_truth.source_search.id_contract import decode_assessment
from guardian_truth.source_search.pipeline import decode_model_object, TOOLS, validate_assessment
from guardian_truth.source_search.store import SourceStore, digest

BASE = ROOT / 'outputs/searh_23/source_search_20261002'


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    original = BASE / 'comparison_ids_v5'
    inputs = rows(original / 'inputs.jsonl')
    predictions = rows(original / 'predictions.jsonl')
    score = json.loads((original / 'score.json').read_text(encoding='utf-8'))
    gold = {r['id']: r['gold'] for r in score['arms']['direct']['cases']}
    by_id = {r['id']: r for r in inputs}
    output = ROOT / 'outputs/searh_23/v10/preflight'
    output.mkdir(parents=True, exist_ok=True)
    cases, hashes, policy_hashes, sizes = [], defaultdict(list), defaultdict(list), []
    usage = defaultdict(list)
    totals = {arm: Counter() for arm in ('direct', 'search')}
    transfer = {}
    with zipfile.ZipFile(original / 'real46_artifacts.zip') as bundle:
        for row in predictions:
            source = by_id[row['case_id']]
            ref = row['source_archive']
            archived_raw = json.loads(bundle.read('source_stores/' + ref['raw_file']))
            index = json.loads(bundle.read('source_stores/' + ref['index_file']))
            if digest(archived_raw) != ref['source_sha256'] or digest(index) != ref['index_sha256']:
                raise ValueError('Archived source mismatch')
            if archived_raw != {k: source[k] for k in ('prompt', 'response')}:
                raise ValueError('Archive differs from frozen original input')
            store = SourceStore(source)
            store.sources, store.quotes = index['sources'], index['quotes']
            catalog = parse_catalog(store.history_events, source['prompt'])
            if row['mode'] == 'direct':
                systems = [e.text for e in store.history_events if e.role == 'system']
                system = '\n'.join(systems)
                normalized = re.sub(r'\s+', ' ', system).strip()
                sha = hashlib.sha256(normalized.encode('utf-8')).hexdigest()
                hashes[sha].append(row['case_id'])
                policy = re.search(r'<policy>([\s\S]*?)</policy>', system)
                if policy:
                    ph = hashlib.sha256(re.sub(r'\s+', ' ', policy[1]).strip().encode('utf-8')).hexdigest()
                    policy_hashes[ph].append(row['case_id'])
                size = len((source['prompt'] + source['response']).encode('utf-8'))
                sizes.append({'case_id': row['case_id'], 'raw_utf8_bytes': size,
                    'above_direct_max_bytes_400000': size > 400000,
                    'catalog_evaluator_tool_overlap': sorted(set(catalog.tools) & set(TOOLS))})
            votes = []
            for event in row['module_trace']:
                model = event.get('model', {})
                usage[row['mode']].append(model.get('usage', {}))
                try:
                    obj = decode_model_object(model.get('content', ''))
                except (ValueError, TypeError):
                    continue
                if isinstance(obj, dict) and isinstance(obj.get('assessment'), dict):
                    votes.append((event, obj['assessment']))
            structural = row.get('coverage', {}).get('structural') == 'confirmed_hit'
            vote = votes[-1][1] if votes else None
            decision = 'ERROR' if structural else vote['decision'] if vote else 'NO_ASSESSMENT'
            label = gold[row['case_id']]
            bucket = ('TP' if label else 'FP') if decision == 'ERROR' else (
                ('FN' if label else 'TN') if decision == 'NO_ERROR' else decision + ('_POSITIVE' if label else '_NEGATIVE'))
            totals[row['mode']][bucket] += 1
            artifacts, empty = [], []
            technical_replay = None
            technical_error = None
            if vote:
                try:
                    normalized_vote = decode_assessment(store, vote)
                    technical_replay = validate_assessment(store, normalized_vote)
                except (ValueError, TypeError, KeyError) as exc:
                    technical_error = str(exc)
                # Existing validator only: do not implement A1 before the audit stop.
                saved = votes[-1][0].get('assessment_validation')
                if saved and saved.get('reason') != 'unread_material_query_remainder' and (
                        technical_replay is None or technical_replay['decision'] != saved['decision']):
                    raise ValueError('Existing technical validator differs from saved trace: ' + row['case_id'])
                for name, check in vote.get('checks', {}).items():
                    if check['status'] != 'OPEN' and not check.get('evidence_ids'):
                        empty.append({'question': name, 'status': check['status']})
                for ordinal, finding in enumerate(vote.get('findings', [])):
                    text = finding.get('explanation', '')
                    names = [name for name in TOOLS if re.search(r'(?<![\w])' + re.escape(name) + r'(?![\w])', text)]
                    absent = sorted(set(names) - set(catalog.tools))
                    if absent:
                        artifacts.append({'finding': ordinal, 'operation_names_absent_from_catalog': absent,
                            'explanation': text})
            case = {'case_id': row['case_id'], 'arm': row['mode'], 'gold': label,
                'structural': structural, 'raw_decision': decision, 'raw_bucket': bucket,
                'saved_decision': row['decision'],
                'old_validator_reproduced_decision': technical_replay['decision'] if technical_replay else None,
                'old_validator_technical_error': technical_error,
                'stop_reason': row.get('coverage', {}).get('stop_reason'),
                'empty_closed_checks': empty, 'evaluator_artifact_candidates': artifacts,
                'raw_explanation': vote.get('explanation') if vote else None,
                'finding_explanations': [f.get('explanation') for f in vote.get('findings', [])] if vote else [],
                'request_bytes': [t.get('request_bytes') for t in row['module_trace']]}
            cases.append(case)
    for name in ('transfer_ids_followup_v1', 'transfer_ids_explicit_intent_v1'):
        path = BASE / name
        labels = rows(path / 'author_review_queue.jsonl')
        transfer[name] = {'inputs': len(rows(path / 'inputs.jsonl')),
            'author_label_counts': dict(Counter(str(r['label']) for r in labels)),
            'review_status': dict(Counter(r['human_review_status'] for r in labels)),
            'groups': dict(Counter(r['group'] for r in labels)),
            'inputs_sha256': file_hash(path / 'inputs.jsonl'),
            'runtime_results_available_locally': (path / 'predictions.jsonl').exists()}
    initial = rows(BASE / 'transfer_ids_followup_v1/inputs.jsonl')
    changed = rows(BASE / 'transfer_ids_explicit_intent_v1/inputs.jsonl')
    unchanged_count = sum(a['prompt'] == b['prompt'] and a['response'] == b['response'] for a, b in zip(initial, changed, strict=True))
    provider_usage = {}
    for arm, values in usage.items():
        provider_usage[arm] = {'model_records': len(values), 'usage_field_names': sorted({k for v in values for k in v}),
            'sum': {k: sum(v.get(k, 0) for v in values if isinstance(v.get(k, 0), (int, float))) for k in sorted({k for v in values for k in v})}}
    direct_prompt_tokens = [t['model']['usage']['prompt_tokens'] for r in predictions
        if r['mode'] == 'direct' for t in r['module_trace']]
    report = {'scope': 'V10_STEP_ZERO_READ_ONLY_AUDIT_OLD_V5_OUTPUTS_NOT_A1_OR_NEW_INFERENCE',
        'starting_commit': '9e6e8821e6567c5eea00f5d9525867f019cadb77',
        'source_files_sha256': {fn: file_hash(original / fn) for fn in ('inputs.jsonl', 'predictions.jsonl', 'score.json', 'real46_artifacts.zip')},
        'new_http_attempts': 0, 'new_model_tokens': 0,
        'raw_proposal_counts_including_structural': {a: dict(c) for a, c in totals.items()},
        'saved_counts': {a: v['counts'] for a, v in score['arms'].items()},
        'normalized_full_system_hashes': dict(hashes), 'normalized_policy_tag_hashes': dict(policy_hashes),
        'normalization': 'Collapse whitespace only; no domain, case, date, persona, or tool deletion.',
        'raw_utf8_size_summary': {'min': min(r['raw_utf8_bytes'] for r in sizes),
            'max': max(r['raw_utf8_bytes'] for r in sizes),
            'mean': sum(r['raw_utf8_bytes'] for r in sizes) / len(sizes),
            'above_400000': sum(r['above_direct_max_bytes_400000'] for r in sizes)},
        'sizes': sizes, 'trace_provider_usage_including_cache': provider_usage,
        'direct_prompt_tokens_from_provider': {'min': min(direct_prompt_tokens),
            'max': max(direct_prompt_tokens), 'mean': sum(direct_prompt_tokens) / len(direct_prompt_tokens)},
        'transfer_banks': transfer, 'explicit_intent_changed_inputs': len(initial) - unchanged_count,
        'instruction_sha256': file_hash(Path('A:/GIS_Загрузки/PROMPT_guardian_v10_fix_and_policy_table.md')),
        'stopping_status': 'STOPPED_AT_STEP_ZERO_PER_INSTRUCTION_SECTION_6_1',
        'blocking_discrepancies': [
            'Section 0.4 asserts no negative controls; both frozen transfer banks contain four author-negative inputs.',
            'Section 0.2 describes about 9k tokens; direct provider input usage ranges from 5149 to 79598 tokens.',
            'A2 literal ban on all TOOLS names in FINAL conflicts with preserving original inputs whose examined catalog includes calculate.'
        ],
        'direct_fn_cases': [r for r in cases if r['arm'] == 'direct' and r['raw_bucket'] == 'FN'],
        'search_raw_error_cases': [r for r in cases if r['arm'] == 'search' and r['raw_decision'] == 'ERROR' and not r['structural']],
        'cases': cases}
    (output / 'audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('raw_proposal_counts_including_structural', 'saved_counts', 'raw_utf8_size_summary', 'trace_provider_usage_including_cache', 'transfer_banks', 'explicit_intent_changed_inputs')}, ensure_ascii=True, indent=2))
    print('normalized_full_system_hash_count', len(hashes), 'normalized_policy_tag_hash_count', len(policy_hashes))
    for r in report['direct_fn_cases']:
        print('DIRECT_FN', json.dumps({'id': r['case_id'], 'explanation': r['raw_explanation']}, ensure_ascii=True))
    for r in report['search_raw_error_cases']:
        print('SEARCH_ERROR', json.dumps({k: r[k] for k in ('case_id', 'raw_bucket', 'evaluator_artifact_candidates', 'finding_explanations')}, ensure_ascii=True))


if __name__ == '__main__':
    main()
