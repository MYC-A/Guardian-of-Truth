"""Recheck identical native-format safety diagnostics after the v4 code fix.

The immutable 2087b088 evidence file remains unchanged. This is a development
regression replay, not a new independent benchmark or whole-response score.
"""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
from audit_consent_enhanced_2087b088 import inspect, row


def main():
    old = json.loads((ROOT / 'outputs/searh_23/v11/consent_enhanced_2087b088_audit.json').read_text(encoding='utf-8'))
    results = []
    for c in old['diagnostics']:
        fixed = inspect(c['fixture'])
        expected = c['expected_consent']
        actual = fixed['enhanced']
        unsafe = actual['status'] == 'RESOLVED' and actual['value'] != expected
        if unsafe:
            raise ValueError('unsafe_code_certificate_remains:' + c['id'])
        results.append({'id': c['id'], 'expected_consent': expected,
                        'previous': c['enhanced'], 'fixed': fixed['enhanced']})
    real = []
    from consent_pair_v2_probe import read
    frozen = read(ROOT / 'outputs/searh_23/v11/consent_pair_probe/freeze.json')
    for c in frozen['cases']:
        if c['kind'] != 'REAL_LABEL_FREE':
            continue
        real.append({'id': c['id'], 'applicable': c['explicit_confirmation_scope']['selected'],
                     **inspect(c['row'], c['target'])})
    positive = inspect(row('Confirm apply_a: {"record_id":"X","amount":2}?',
                           {'record_id': 'X', 'amount': 2}))
    if positive['enhanced']['value'] is not True:
        raise ValueError('complete_explicit_certificate_regressed')
    report = {'version': 'certified-enhanced-v4-safety', 'new_http_attempts': 0,
        'scope': 'CONSENT_ONLY_DEVELOPMENT_REGRESSION_REPLAY',
        'previous_commit': old['audited_commit'], 'diagnostics': results,
        'real84_code_witness': real, 'complete_explicit_positive': positive,
        'unsafe_resolved_remaining': [], 'free_prose_model_channel': 'consent_pair_v4 SHADOW only'}
    path = ROOT / 'outputs/searh_23/v11/consent_safe_v4_audit.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'unsafe_resolved_remaining': 0, 'rechecked_diagnostics': len(results),
                      'real_positions': len(real), 'applicable_positions': sum(c['applicable'] for c in real),
                      'complete_explicit_positive': True}))


if __name__ == '__main__':
    main()
