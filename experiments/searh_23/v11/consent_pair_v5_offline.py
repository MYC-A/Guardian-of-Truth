"""No-network V5 development replay of immutable V4/V3 model responses.

The program has no transport client, credentials, remote runner or API command.
freeze must be committed before replay. Results measure admission fixes on already
viewed answers, not new inference or generalization of natural-language semantics.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
from guardian_truth.policy_table_v11 import consent_pair_v5 as semantic
from guardian_truth.source_search.pipeline import decode_model_object
from guardian_truth.source_search.store import SourceStore, digest

VERSION = 'consent-pair-offline/5'
RUN = ROOT / 'outputs/searh_23/v11/consent_pair_v5_offline'
V4 = ROOT / 'outputs/searh_23/v11/consent_pair_v4_83c29366_complete.zip'
V3 = ROOT / 'outputs/searh_23/v11/consent_pair_v3_2d4f4d6e_complete.zip'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def archived(path, name):
    with ZipFile(path) as archive:
        return json.loads(archive.read(name))


def blob(path):
    return subprocess.check_output(['git', 'hash-object', str(path)], cwd=ROOT, text=True).strip()


def freeze():
    path = RUN / 'freeze.json'
    if path.exists():
        raise ValueError('freeze_exists_use_new_version')
    parent = archived(V4, 'consent_pair_v4_probe/freeze.json')
    paths = list((ROOT / 'src/guardian_truth').rglob('*.py')) + [Path(__file__),
        ROOT / 'tests/test_policy_table_v11_consent_pair_v5.py']
    frozen = {'version': VERSION, 'declaration': 'POST_RESULT_DEVELOPMENT_REPLAY_NOT_UNSEEN_TRANSFER',
        'sources': {p.relative_to(ROOT).as_posix(): blob(p) for p in paths},
        'archives': {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in (V4, V3)},
        'case_count': len(parent['cases']), 'new_http_attempts': 0,
        'model_prompt_changed': False, 'target_values_exposed': False,
        'changes': ['MIXED_EVIDENCE_INHERITANCE_PRESERVES_EXPLICIT_INNER_SOURCES',
                    'STRICT_TYPED_WHOLE_ARGUMENT_JSON_SOURCE', 'CONFLICTING_SOURCE_JSON_BLOCKS_SCALAR_FALLBACK'],
        'semantic_limit': 'MODEL_ACTOR_SCOPE_AND_REPLY_CLASSIFICATIONS_REMAIN_UNPROVEN',
        'decision_status': 'SHADOW_ONLY', 'gold_opened': False}
    write(path, frozen)
    return {'version': VERSION, 'cases': frozen['case_count'], 'new_http_attempts': 0}


def verify():
    path = RUN / 'freeze.json'
    frozen = read(path)
    committed = json.loads(subprocess.check_output(['git', 'show', 'HEAD:' + path.relative_to(ROOT).as_posix()], cwd=ROOT))
    if frozen != committed or frozen['version'] != VERSION:
        raise ValueError('offline_freeze_not_committed')
    for rel, expected in frozen['sources'].items():
        if blob(ROOT / rel) != expected or subprocess.check_output(
                ['git', 'rev-parse', 'HEAD:' + rel], cwd=ROOT, text=True).strip() != expected:
            raise ValueError('offline_frozen_source_changed:' + rel)
    for rel, expected in frozen['archives'].items():
        if hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() != expected:
            raise ValueError('offline_source_archive_changed:' + rel)
    return frozen


def raw_response(parent, older, case, model):
    if not case['target_valid'] or not case['proposal_source_id']:
        return None
    if case['inference_mode'] == 'FRESH_V4':
        source, selected, path, directory = parent, case, V4, 'consent_pair_v4_probe'
    else:
        source, path, directory = older, V3, 'consent_pair_v3_probe'
        selected = next(c for c in source['cases'] if c['id'] == case['id'])
        if digest({'row': selected['row'], 'target': selected['target']}) != digest(
                {'row': case['row'], 'target': case['target']}):
            raise ValueError('replay_case_source_changed')
    uid = digest({'messages': source['requests'][selected['packet_sha256']],
                  'model': model, 'version': source['version']})
    return archived(path, directory + '/replies/' + uid + '.json')


def model_result(case, model, raw):
    store, target = SourceStore(case['row']), case['target']
    if raw is None:
        admitted = {'valid': False, 'reason': 'malformed_target_or_no_proposal', 'plans': [], 'discarded': []}
    else:
        decoded, decode_error = None, None
        try:
            decoded = decode_model_object(raw.get('content')) if raw['status'] == 'OK' else None
            json.dumps(decoded, allow_nan=False)
        except (ValueError, TypeError, RecursionError) as exc:
            decoded, decode_error = None, type(exc).__name__
        choices = raw.get('provider_response', {}).get('choices') or [{}]
        if choices[0].get('finish_reason') in ('length', 'max_tokens'):
            decoded = None
        admitted = semantic.admit(decoded, store, target, case['proposal_source_id'])
        if decode_error:
            admitted['decode_error'] = decode_error
    return {'family': model['family'], 'admission': admitted,
        'verdict': semantic.verdict(admitted, store, target),
        'parent_attempt_id': raw.get('attempt_id') if raw else None, 'new_http_attempts': 0}


def failure(case, decision):
    value = decision['value']
    return (value == 'TRUE' if case['expected'] == 'NEVER_TRUE' else
            case['expected'] is not None and value != 'UNRESOLVED' and value != case['expected'])


def replay():
    frozen = verify()
    parent = archived(V4, 'consent_pair_v4_probe/freeze.json')
    older = archived(V3, 'consent_pair_v3_probe/freeze.json')
    if parent['models'] != older['models']:
        raise ValueError('replay_models_changed')
    old_result = archived(V4, 'consent_pair_v4_probe/result.json')
    baseline = {r['id']: r for r in old_result['rows']}
    result = {'version': VERSION, 'freeze_sha256': digest(frozen), 'rows': [],
              'new_http_attempts': 0, 'new_api_tokens': 0, 'stop_reason': None}
    for case in parent['cases']:
        row = {'id': case['id'], 'parent_inference_mode': case['inference_mode'],
               'inference_mode': 'POST_RESULT_DEVELOPMENT_REPLAY', 'models': []}
        for model in parent['models']:
            row['models'].append(model_result(case, model, raw_response(parent, older, case, model)))
        row['consensus'] = semantic.agreement(row['models'])
        row['baseline_consensus'] = baseline[case['id']]['consensus']
        result['rows'].append(row)
        if failure(case, row['consensus']):
            result['stop_reason'] = 'WRONG_RESOLVED_CONSENSUS:' + case['id']
            break
    write(RUN / 'result.json', result)
    indexed = {r['id']: r for r in result['rows']}
    report = {'version': VERSION, 'complete': len(indexed) == len(parent['cases']),
        'new_http_attempts': 0, 'new_api_tokens': 0, 'stop_reason': result['stop_reason'],
        'declaration': frozen['declaration'], 'groups': {}, 'changed': [],
        'whole_detector_improvement_measured': False, 'code_proof': False, 'gold_opened': False}
    for name, predicate in {
        'REAL_LABEL_FREE': lambda c: c['kind'] == 'REAL_LABEL_FREE',
        'M1_REPLAY': lambda c: c['kind'] == 'FRESH_M1',
        'OLD53_REPLAY': lambda c: c['kind'] == 'SYNTHETIC' and c['inference_mode'] == 'REPLAY_V3',
        'PROSPECTIVE12_NOW_DEVELOPMENT_REPLAY': lambda c: c['id'] in parent['prospective_case_ids'],
    }.items():
        pairs = [(case, indexed[case['id']]) for case in parent['cases'] if predicate(case) and case['id'] in indexed]
        values = Counter(row['consensus']['value'] for _, row in pairs)
        report['groups'][name] = {'completed': len(pairs), 'TRUE': values['TRUE'], 'FALSE': values['FALSE'],
            'UNKNOWN': values['UNRESOLVED'], 'wrong_resolved': [c['id'] for c, r in pairs if failure(c, r['consensus'])],
            'cases': [{'id': c['id'], 'expected': c['expected'], 'value': r['consensus']['value'],
                       'model_reasons': r['consensus']['model_reasons']} for c, r in pairs]}
    for case in parent['cases']:
        row = indexed.get(case['id'])
        if row and row['consensus']['value'] != row['baseline_consensus']['value']:
            report['changed'].append({'id': case['id'], 'expected': case['expected'],
                'old': row['baseline_consensus']['value'], 'new': row['consensus']['value'],
                'model_reasons': row['consensus']['model_reasons']})
    write(RUN / 'score.json', report)
    return {key: report[key] for key in ('complete', 'stop_reason', 'new_http_attempts', 'changed')} | {
        'groups': {k: {x: v[x] for x in ('completed', 'TRUE', 'FALSE', 'UNKNOWN', 'wrong_resolved')}
                   for k, v in report['groups'].items()}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('freeze', 'verify', 'replay'))
    args = parser.parse_args()
    value = freeze() if args.command == 'freeze' else {'valid': True} if args.command == 'verify' and verify() else replay()
    print(json.dumps(value, ensure_ascii=False))
