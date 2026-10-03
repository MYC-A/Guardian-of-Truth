"""Frozen v4: explicit cached replay plus a small prospective fresh API cohort.

No replay receipt is counted as a new HTTP attempt. Previous model replies and
algorithms stay immutable. Source-format safety fixes are a separate code gate.
"""
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

import consent_pair_v2_probe as runner
from consent_pair_v2_extra import cases as v2_cases
from consent_pair_v3_extra import cases as v3_cases
from consent_pair_v4_extra import cases as prospective_cases
from guardian_truth.policy_table_v11 import consent_pair_v4
from guardian_truth.source_search.store import digest

runner.RUN = runner.ROOT / 'outputs/searh_23/v11/consent_pair_v4_probe'
runner.VERSION = 'consent-pair-probe/4'
runner.semantic = consent_pair_v4
runner.extra_cases = lambda: v2_cases() + v3_cases() + prospective_cases()
PARENT = runner.ROOT / 'outputs/searh_23/v11/consent_pair_v3_2d4f4d6e_complete.zip'
FRESH_REAL = {'airline__7::t6/h13', 'airline__9::t6/t0', 'airline__23::t10/t0',
              'retail__29::t13/h29', 'retail__27::t10/t0', 'retail__27::t10/t1'}
base_freeze, base_verify, base_score = runner.freeze, runner.verify, runner.score


def parent_data():
    with ZipFile(PARENT) as archive:
        frozen = json.loads(archive.read('consent_pair_v3_probe/freeze.json'))
    return frozen


def parent_raw(frozen, case, model):
    parent = next(c for c in frozen['cases'] if c['id'] == case['id'])
    if digest({'row': parent['row'], 'target': parent['target']}) != digest(
            {'row': case['row'], 'target': case['target']}):
        raise ValueError('replay_source_or_target_changed')
    if not parent['target_valid'] or not parent['proposal_source_id']:
        return None
    uid = digest({'messages': frozen['requests'][parent['packet_sha256']],
                  'model': model, 'version': frozen['version']})
    with ZipFile(PARENT) as archive:
        return json.loads(archive.read('consent_pair_v3_probe/replies/' + uid + '.json'))


def freeze():
    base_freeze()
    path = runner.RUN / 'freeze.json'
    frozen = runner.read(path)
    fresh_ids = {'new/' + c['id'] for c in prospective_cases()} | FRESH_REAL
    frozen['fresh_case_ids'] = sorted(fresh_ids)
    packets = {c['packet_sha256'] for c in frozen['cases'] if c['id'] in fresh_ids
               and c['target_valid'] and c['proposal_source_id']}
    # Every target sharing a selected fresh packet gets the same inference mode.
    for c in frozen['cases']:
        c['inference_mode'] = 'FRESH_V4' if c.get('packet_sha256') in packets else 'REPLAY_V3'
    frozen['fresh_case_ids'] = sorted(c['id'] for c in frozen['cases'] if c['inference_mode'] == 'FRESH_V4')
    frozen['max_new_http'] = len(packets) * len(frozen['models'])
    if frozen['max_new_http'] != 34:
        raise ValueError('prospective_inference_plan_changed')
    frozen['replay_parent'] = {'version': 'consent-pair-probe/3',
        'freeze_commit': '2d4f4d6e', 'archive': PARENT.relative_to(runner.ROOT).as_posix(),
        'sha256': hashlib.sha256(PARENT.read_bytes()).hexdigest()}
    frozen['prospective_case_ids'] = sorted('new/' + c['id'] for c in prospective_cases())
    frozen['fresh_real_selection'] = 'DEVELOPMENT_RECONFIRMATION_OF_SIX_SOURCE_CHECKED_REPLAY_TRUE_NOT_UNSEEN_TEST'
    frozen['changes'] = ['NORMALIZE_CONTAINER_CITATIONS_WITH_INDEPENDENT_LEAF_VALIDATION',
                         'REMOVE_UNCERTIFIED_REGEX_RESULTS_FROM_CODE_WITNESS']
    frozen['declaration'] = 'MIXED_DEVELOPMENT_REPLAY_AND_PROSPECTIVE_CONTROLS_MODEL_SEMANTICS_NOT_CODE_PROOF'
    for source in (Path(__file__), Path(__file__).with_name('consent_pair_v4_extra.py'),
            Path(__file__).with_name('consent_pair_v3_extra.py'),
            runner.ROOT / 'tests/test_policy_table_v11_consent_pair_v4.py',
            runner.ROOT / 'tests/test_policy_table_v11_consent_enhanced_safe.py', PARENT):
        frozen['sources'][source.relative_to(runner.ROOT).as_posix()] = runner.blob(source)
    runner.write(path, frozen)
    return {k: frozen[k] for k in ('version', 'unique_packet_count', 'max_new_http')}


def verify():
    frozen = base_verify()
    if hashlib.sha256(PARENT.read_bytes()).hexdigest() != frozen['replay_parent']['sha256']:
        raise ValueError('replay_archive_changed')
    parent = parent_data()
    if frozen['models'] != parent['models']:
        raise ValueError('replay_models_changed')
    parent_ids = {c['id'] for c in parent['cases']}
    for c in frozen['cases']:
        if c['inference_mode'] == 'REPLAY_V3' and c['id'] not in parent_ids:
            raise ValueError('prospective_case_cannot_be_replayed')
    return frozen


def score(frozen, result):
    report = base_score(frozen, result)
    indexed = {r['id']: r for r in result['rows']}
    report['cohorts_by_inference_mode'] = {}
    for mode in ('REPLAY_V3', 'FRESH_V4'):
        for kind in ('SYNTHETIC', 'REAL_LABEL_FREE', 'FRESH_M1'):
            cases = [c for c in frozen['cases'] if c['inference_mode'] == mode and c['kind'] == kind]
            rows = [(c, indexed[c['id']]) for c in cases if c['id'] in indexed]
            values = runner.Counter(r['consensus']['value'] for _, r in rows)
            report['cohorts_by_inference_mode'][mode + '/' + kind] = {
                'expected_cases': len(cases), 'completed': len(rows),
                'TRUE': values['TRUE'], 'FALSE': values['FALSE'], 'UNKNOWN': values['UNRESOLVED'],
                'wrong_resolved': [c['id'] for c, r in rows if runner.is_failure(c, r['consensus'])]}
    report['replay_parent'] = frozen['replay_parent']
    report['prospective_case_ids'] = frozen['prospective_case_ids']
    report['replay_http_attempts'] = 0
    runner.write(runner.RUN / 'score.json', report)
    return report


def run():
    frozen = verify()
    path = runner.RUN / 'result.json'
    result = runner.read(path) if path.exists() else {
        'freeze_sha256': digest(frozen), 'rows': [],
        'budget_before': runner.transport(frozen, frozen['models'][0]).snapshot()}
    if result['freeze_sha256'] != digest(frozen):
        raise ValueError('resume_freeze_changed')
    if result.get('stop_reason'):
        return score(frozen, result)
    parent = parent_data()
    done = {r['id'] for r in result['rows']}
    for case in frozen['cases']:
        if case['id'] in done:
            continue
        row = {'id': case['id'], 'models': [], 'inference_mode': case['inference_mode']}
        for model in frozen['models']:
            raw = None
            if case['inference_mode'] == 'REPLAY_V3':
                raw = parent_raw(parent, case, model)
            elif case['target_valid'] and case['proposal_source_id']:
                messages = frozen['requests'][case['packet_sha256']]
                uid = digest({'messages': messages, 'model': model, 'version': runner.VERSION})
                cache = runner.RUN / 'replies' / (uid + '.json')
                raw = runner.read(cache) if cache.exists() else runner.transport(frozen, model)(
                    messages, fresh_sample=runner.VERSION)
                if not cache.exists():
                    runner.write(cache, raw)
                if raw['status'] != 'OK':
                    result['stop_reason'] = raw.get('reason', raw['status'])
                    break
            row['models'].append(runner.model_result(case, model, raw))
        if len(row['models']) != len(frozen['models']):
            result['partial_row'] = row
            break
        row['consensus'] = consent_pair_v4.agreement(row['models'])
        result['rows'].append(row)
        if runner.is_failure(case, row['consensus']):
            result['stop_reason'] = 'WRONG_RESOLVED_CONSENSUS:' + case['id']
        result['budget_after'] = runner.transport(frozen, frozen['models'][0]).snapshot()
        runner.write(path, result)
        if result.get('stop_reason'):
            break
    result['budget_after'] = runner.transport(frozen, frozen['models'][0]).snapshot()
    runner.write(path, result)
    return score(frozen, result)


runner.freeze, runner.verify, runner.run, runner.score = freeze, verify, run, score
if __name__ == '__main__':
    runner.main()
