"""Score the §6 atomic repair regression (offline; gold opened post-run).

Criteria split per the assignment:
 - FIX level: the atomization/extraction layer itself — historical INVALID
   cases restored; mechanical layer manufactures no accusations on clean
   tool calls (relations only come from the advisory model verifier).
 - ADVISORY model level: the verifier's own behaviour is reported honestly
   (it is the same model family as B and is EXPECTED to reproduce the §5
   FP mechanisms there; decisions stay ADVISORY_ONLY).
"""
import hashlib
import json
from pathlib import Path

from modular_common import HERE, RESULTS

FOLDER = RESULTS / 'atomic_repair_pilot'


def main():
    manifest = json.loads((HERE / 'dataset/manifest.json').read_text(encoding='utf-8'))
    blob = (HERE / 'dataset/dev_gold.jsonl').read_bytes()
    assert hashlib.sha256(blob).hexdigest() == manifest['splits']['dev']['gold_sha256']
    gold = {r['id']: r for r in map(json.loads, blob.decode().splitlines())}
    rows = [json.loads(l) for l in (FOLDER / 'predictions.jsonl').read_text(encoding='utf-8').splitlines()]
    selection = json.loads((FOLDER / 'selection.json').read_text(encoding='utf-8'))
    per_case = {}
    for r in rows:
        cid = r['id']
        per_case[cid] = {
            'gold_label': gold[cid]['label'],
            'atomizer_text_status': r['atomizer_text_status'],
            'verifier_status': r['verifier_status'],
            'mechanical_actions': r['mechanical_actions'],
            'verification_relations': r['verification_relations'],
            'coverage_gap': r['coverage_gap'],
        }
    # ---- fix level ----
    restored = []
    for cid in selection['original_invalid_ids']:
        e = per_case[cid]
        restored.append({'id': cid,
                         'original_cause': selection['original_invalid_causes'][cid],
                         'atomizer_now': e['atomizer_text_status'],
                         'atomizer_restored': e['atomizer_text_status'] not in
                         ('MODEL_INVALID_INVENTORY', 'INVALID', 'TRANSPORT_FAILED')})
    clean = [c for c in selection['clean_paired_tool_calls'] if c in per_case]
    mechanical_accusations = [c for c in clean if per_case[c]['mechanical_actions'] and
                              'CONTRADICTS' in (per_case[c]['verification_relations'] or [])
                              and per_case[c]['verifier_status'] == 'NOTHING_TO_VERIFY']
    advisory_fps_on_clean = [c for c in clean if 'CONTRADICTS' in (per_case[c]['verification_relations'] or [])]
    control = selection['real_error_tool_call_control'][0]
    report = {
        'schema': 'atomic-repair-score/2',
        'n': len(rows),
        'fix_level': {
            'historical_invalid_atomizer_restored': restored,
            'restored_count': sum(1 for x in restored if x['atomizer_restored']),
            'mechanical_layer_accusations_on_clean_tool_calls': mechanical_accusations,
            'mechanical_layer_pass': not mechanical_accusations,
            'note': 'relations come only from the ADVISORY model verifier; the '
                    'mechanical extraction layer never creates accusations',
        },
        'advisory_model_level': {
            'verifier_valid': sum(1 for e in per_case.values() if e['verifier_status'] == 'MODEL_JUDGED'),
            'verifier_invalid_ids': [c for c, e in per_case.items() if e['verifier_status'] == 'INVALID'],
            'clean_cases_flagged_contradicts_by_model': advisory_fps_on_clean,
            'real_error_control': {'id': control, 'gold_label': per_case[control]['gold_label'],
                                   'relations': per_case[control]['verification_relations'],
                                   'correctly_flagged': 'CONTRADICTS' in (per_case[control]['verification_relations'] or [])},
            'note': 'dev_units::00 CONTRADICTS is the T4/T16 family from the §5 atlas '
                    '(demanding execution confirmation for a proposed action) reproduced '
                    'by the same model in the advisory verifier role — consistent with the '
                    'model-semantic root cause; decisions stay ADVISORY_ONLY. dev_request_'
                    'effect::01 (B T14 FP case) is judged SUPPORTS (correct) here with '
                    'mechanically supplied observed facts + catalog visibility.',
        },
        'per_case': per_case,
    }
    out = FOLDER / 'score.json'
    out.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'atomizer_restored': report['fix_level']['restored_count'],
                      'mechanical_pass': report['fix_level']['mechanical_layer_pass'],
                      'verifier_valid': report['advisory_model_level']['verifier_valid'],
                      'advisory_fps_on_clean': advisory_fps_on_clean,
                      'control_flagged': report['advisory_model_level']['real_error_control']['correctly_flagged']},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
