"""Frozen one-proposal consent comparison; development replay, not unseen gold.

Only run contacts APIs. One attempt per unique packet/model, no retries. Existing
shared cost ledger and quota breakers are preserved. No predictor integration.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(Path(__file__).parent))
from guardian_truth.source_search.store import SourceStore, digest
from guardian_truth.source_search.id_contract import native_target_inventory
from guardian_truth.source_search.pipeline import decode_model_object
from guardian_truth.policy_table_v11 import consent_pair_v2 as semantic
from guardian_truth.policy_table_v11.transport import Transport
from consent_pair_probe import write, read, m1_mutant
from consent_pair_v2_extra import cases as extra_cases

RUN = ROOT / 'outputs/searh_23/v11/consent_pair_v2_probe'
OLD = ROOT / 'outputs/searh_23/v11/consent_pair_probe'
VERSION = 'consent-pair-probe/2'
MODELS = [
    {'provider': 'ollama', 'model': 'gpt-oss:120b', 'family': 'gpt-oss', 'reasoning_effort': 'low'},
    {'provider': 'ollama', 'model': 'gemma4:31b', 'family': 'gemma', 'reasoning_effort': None},
]


def blob(path):
    return subprocess.check_output(['git', 'hash-object', str(path)], cwd=ROOT, text=True).strip()


def synthetic(item):
    row = item['row']
    store = SourceStore(row)
    return {'id': 'new/' + item['id'], 'kind': 'SYNTHETIC', 'row': row,
            'target': native_target_inventory(store)[-1], 'expected': item['expected'],
            'expectation_scope': 'ACTION_CONSENT_ONLY', 'note': item['note']}


def freeze():
    if (RUN / 'freeze.json').exists():
        raise ValueError('freeze_exists_use_new_version')
    old = read(OLD / 'freeze.json')
    contrast = [dict(c, expected=c.get('source_qualified_expected', c['expected']))
                for c in old['cases'] if c['kind'] == 'SYNTHETIC']
    contrast += [synthetic(item) for item in extra_cases()]
    real = [c for c in old['cases'] if c['kind'] == 'REAL_LABEL_FREE'
            and c['explicit_confirmation_scope']['selected']]
    if len(real) != 19:
        raise ValueError('real19_inventory_changed')
    mutants = []
    for c in real:
        s, t, removed = m1_mutant(c)
        mutants.append({'id': 'M1/' + c['id'], 'kind': 'FRESH_M1',
            'row': {'id': c['row']['id'], **s.raw}, 'target': t,
            'expected': 'NEVER_TRUE', 'removed_user_events': removed,
            'expectation_scope': 'NO_AUTHORIZATION_FROM_REMOVED_SOURCE'})
    cohort = contrast + real + mutants
    if len({c['id'] for c in cohort}) != len(cohort):
        raise ValueError('duplicate_cases')
    requests = {}
    for c in cohort:
        s = SourceStore(c['row'])
        t = c['target']
        source = s.sources[t['source_id']]
        event = (s.history_events if source['document'] == 'prompt' else s.target_events)[source['event']]
        c['source_sha256'] = s.source_sha256
        c['target_valid'] = event.json_valid and isinstance(event.value, dict)
        c['proposal_source_id'] = semantic.selected_proposal(s, t)
        if c['target_valid'] and c['proposal_source_id']:
            messages = semantic.request(s, t)
            c['packet_sha256'] = digest(messages)
            requests[c['packet_sha256']] = messages
    paths = list((ROOT / 'src/guardian_truth').rglob('*.py'))
    paths += [Path(__file__), Path(__file__).with_name('consent_pair_v2_extra.py'),
              Path(__file__).with_name('consent_pair_probe.py'),
              ROOT / 'tests/test_policy_table_v11_consent_pair_v2.py']
    value = {'version': VERSION, 'cases': cohort, 'models': MODELS,
        'sources': {p.relative_to(ROOT).as_posix(): blob(p) for p in paths},
        'requests': requests, 'ledger': '/workspace/guardian/results/v11-policy-table-20261003',
        'limits': {'http': 450, 'tokens': 3000000}, 'max_output_tokens': 8192,
        'timeout': 150, 'retry': 0, 'backend': 'PLAIN_JSON_PROMPT_NO_RESPONSE_FORMAT',
        'unique_packet_count': len(requests), 'max_new_http': len(requests) * len(MODELS),
        'selection': 'V1_REAL19_UNCHANGED_SOURCE_FROZEN_MANUAL_SCOPE_RESEARCH_ONLY',
        'declaration': 'DEVELOPMENT_REPLAY_MODEL_SEMANTICS_NOT_CODE_PROOF',
        'gold_opened': False, 'safety_gate': 'ANY_WRONG_RESOLVED_CONSENSUS_OR_M1_TRUE_STOPS_RUN',
        'scope_limits': ['FULL_EXPLICIT_ARGUMENTS_ONLY', 'NO_PARAMETER_EXEMPTIONS',
                         'NO_REFERENCED_RECEIPT_COMPLETION', 'NO_READ_EFFECT_CONTRACT',
                         'LATEST_ANSWERED_PROPOSAL_ONLY', 'LATER_TEXT_BLOCKS_RESOLUTION']}
    write(RUN / 'freeze.json', value)
    return {k: value[k] for k in ('version', 'unique_packet_count', 'max_new_http')}


def verify():
    path = RUN / 'freeze.json'
    frozen = read(path)
    committed = json.loads(subprocess.check_output(['git', 'show', 'HEAD:' + path.relative_to(ROOT).as_posix()], cwd=ROOT))
    if frozen != committed or frozen['version'] != VERSION or frozen['models'] != MODELS:
        raise ValueError('freeze_not_committed_or_config_changed')
    for rel, expected in frozen['sources'].items():
        if blob(ROOT / rel) != expected:
            raise ValueError('frozen_source_changed:' + rel)
        actual = subprocess.check_output(['git', 'rev-parse', 'HEAD:' + rel], cwd=ROOT, text=True).strip()
        if actual != expected:
            raise ValueError('frozen_code_not_committed:' + rel)
    for case in frozen['cases']:
        if SourceStore(case['row']).source_sha256 != case['source_sha256']:
            raise ValueError('case_source_changed')
    return frozen


def transport(f, model):
    return Transport(f['ledger'], model['provider'], model['model'],
        reasoning_effort=model['reasoning_effort'], max_output_tokens=f['max_output_tokens'],
        timeout=f['timeout'], max_calls=f['limits']['http'], max_tokens=f['limits']['tokens'])


def model_result(case, model, raw):
    store, t = SourceStore(case['row']), case['target']
    if raw is None:
        admission = {'valid': False, 'reason': 'malformed_target_or_no_proposal', 'plans': [], 'discarded': []}
    else:
        decode_error = None
        try:
            decoded = decode_model_object(raw.get('content')) if raw['status'] == 'OK' else None
            json.dumps(decoded, allow_nan=False)
        except (ValueError, TypeError, RecursionError) as exc:
            decoded, decode_error = None, type(exc).__name__
        choices = raw.get('provider_response', {}).get('choices') or [{}]
        if choices[0].get('finish_reason') in ('length', 'max_tokens'):
            decoded = None
        admission = semantic.admit(decoded, store, t, case['proposal_source_id'])
        if decode_error:
            admission['decode_error'] = decode_error
    verdict = semantic.verdict(admission, store, t)
    return {'family': model['family'], 'admission': admission, 'verdict': verdict,
            'attempt_id': raw.get('attempt_id') if raw else None}


def is_failure(case, consensus):
    value = consensus['value']
    if case['expected'] == 'NEVER_TRUE':
        return value == 'TRUE'
    return case['expected'] is not None and value != 'UNRESOLVED' and value != case['expected']


def score(f, result):
    indexed = {r['id']: r for r in result['rows']}
    report = {'version': VERSION, 'complete': len(indexed) == len(f['cases']),
              'stop_reason': result.get('stop_reason'), 'groups': {}, 'families': {},
              'own_cost': {}, 'gold_opened': False, 'decision_status': 'SHADOW_ONLY',
              'code_proof': False, 'whole_detector_improvement_measured': False}
    for kind in ('SYNTHETIC', 'REAL_LABEL_FREE', 'FRESH_M1'):
        cases = [c for c in f['cases'] if c['kind'] == kind]
        rows = [(c, indexed[c['id']]) for c in cases if c['id'] in indexed]
        values = Counter(r['consensus']['value'] for _, r in rows)
        report['groups'][kind] = {'expected_cases': len(cases), 'completed': len(rows),
            'TRUE': values['TRUE'], 'FALSE': values['FALSE'], 'UNKNOWN': values['UNRESOLVED'],
            'wrong_resolved': [c['id'] for c, r in rows if is_failure(c, r['consensus'])],
            'resolved_case_ids': [c['id'] for c, r in rows if r['consensus']['value'] != 'UNRESOLVED'],
            'all_cases_with_reasons': [{'id': c['id'], 'value': r['consensus']['value'],
                'model_reasons': r['consensus'].get('model_reasons'), 'expected': c['expected']}
                for c, r in rows]}
    for model in f['models']:
        pairs = [(c, r) for c in f['cases'] for r in indexed.get(c['id'], {}).get('models', [])
                 if r['family'] == model['family']]
        report['families'][model['family']] = {
            kind: {'values': dict(Counter(r['verdict']['value'] for c, r in pairs if c['kind'] == kind)),
                   'wrong_resolved': [c['id'] for c, r in pairs if c['kind'] == kind and is_failure(c, r['verdict'])],
                   'admission_invalid_reasons': dict(Counter(r['admission'].get('reason') for c, r in pairs
                        if c['kind'] == kind and not r['admission']['valid'])),
                   'discarded_plan_reasons': dict(Counter(p['reason'] for c, r in pairs if c['kind'] == kind
                        for p in r['admission'].get('discarded', [])))}
            for kind in ('SYNTHETIC', 'REAL_LABEL_FREE', 'FRESH_M1')}
    receipts = list((RUN / 'replies').glob('*.json')) if (RUN / 'replies').exists() else []
    attempts = {read(p)['attempt_id']: read(p) for p in receipts if read(p).get('attempt_id') is not None}
    report['own_cost'] = {'http_attempts': len(attempts),
        'known_tokens': sum(r.get('known_tokens', 0) for r in attempts.values()),
        'unknown_upper_bound': sum(r.get('unknown_upper_bound', 0) for r in attempts.values()),
        'http_seconds': sum(r.get('seconds', 0) for r in attempts.values())}
    report['global_budget_before'] = result.get('budget_before')
    report['global_budget_after'] = result.get('budget_after')
    write(RUN / 'score.json', report)
    return report


def run():
    f = verify()
    path = RUN / 'result.json'
    result = read(path) if path.exists() else {'freeze_sha256': digest(f), 'rows': [],
                                             'budget_before': transport(f, f['models'][0]).snapshot()}
    if result['freeze_sha256'] != digest(f):
        raise ValueError('resume_freeze_changed')
    if result.get('stop_reason'):
        return score(f, result)
    done = {r['id'] for r in result['rows']}
    for case in f['cases']:
        if case['id'] in done:
            continue
        row = {'id': case['id'], 'models': []}
        for model in f['models']:
            raw = None
            if case['target_valid'] and case['proposal_source_id']:
                messages = f['requests'][case['packet_sha256']]
                uid = digest({'messages': messages, 'model': model, 'version': VERSION})
                cache = RUN / 'replies' / (uid + '.json')
                if cache.exists():
                    raw = read(cache)
                else:
                    raw = transport(f, model)(messages, fresh_sample=VERSION)
                    write(cache, raw)
                if raw['status'] != 'OK':
                    result['stop_reason'] = raw.get('reason', raw['status'])
                    break
            row['models'].append(model_result(case, model, raw))
        if len(row['models']) != len(f['models']):
            result['partial_row'] = row
            break
        row['consensus'] = semantic.agreement(row['models'])
        result['rows'].append(row)
        if is_failure(case, row['consensus']):
            result['stop_reason'] = 'WRONG_RESOLVED_CONSENSUS:' + case['id']
        result['budget_after'] = transport(f, f['models'][0]).snapshot()
        write(path, result)
        # Progress lives in the artifact, not a stream of polling output.
        if result.get('stop_reason'):
            break
    result['budget_after'] = transport(f, f['models'][0]).snapshot()
    write(path, result)
    return score(f, result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('freeze', 'verify', 'run', 'score'))
    phase = parser.parse_args().phase
    if phase == 'freeze':
        value = freeze()
    elif phase == 'verify':
        f = verify()
        value = {'verified': True, 'cases': len(f['cases']), 'max_new_http': f['max_new_http']}
    elif phase == 'run':
        value = run()
    else:
        value = score(verify(), read(RUN / 'result.json'))
    print(json.dumps(value if phase in ('freeze', 'verify') else {
        k: value[k] for k in ('complete', 'stop_reason', 'groups', 'own_cost')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
