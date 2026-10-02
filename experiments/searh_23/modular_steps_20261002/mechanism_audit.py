"""Offline measured-mechanism census; never triggers model inference."""
from collections import Counter, defaultdict
import argparse
import json
from pathlib import Path
from modular_common import HERE, write


def read(path):
    return list(map(json.loads, path.read_text(encoding='utf-8').splitlines())) if path.exists() else []


def run(root):
    result = {'human_reviewed': False, 'sealed_scored': False, 'modules': {}}
    ccg = read(root / 'ccg_pilot/predictions.jsonl')
    sentences = [s for r in ccg for s in r.get('formulas', [])]
    result['modules']['CCG'] = {'policies_executed': len(ccg), 'source_sentences': sum(len(r['source_sentences']) for r in ccg),
        'semantic_sentence_statuses': dict(Counter(s['status'] for s in sentences)),
        'formula_roots': sum(len(s.get('roots', [])) for s in sentences),
        'native_inference_statuses': dict(Counter(r['native_inference'] for r in ccg)),
        'quality': 'Author pipeline executed, no verified policy semantics or full-policy inference',
        'per_case': [{'id': r['id'], 'sentences': len(r['source_sentences']), 'formulas': r['formulas']} for r in ccg]}
    gold = {r['id']: r for r in read(HERE / 'dataset/native_claims/author_gold.jsonl')}
    native = read(root / 'native_claim_pilot/predictions.jsonl')
    groups = defaultdict(list)
    for r in native:
        expected = gold[r['id']]['relation'] == 'SUPPORTS'
        predicts = r['support_score'] >= .5 if r['support_score'] is not None else None
        groups[r['model']].append({'id': r['id'], 'author_relation': gold[r['id']]['relation'],
            'support_score': r['support_score'], 'correct_support_classification': predicts == expected,
            'truncated': r['truncated']})
    shared = set.intersection(*({r['id'] for r in rows} for rows in groups.values())) if groups else set()
    result['modules']['native_claims'] = {'scope': 'Oracle atom inventory; not autonomous/end-to-end detection',
        'common_paired_ids': sorted(shared), 'models': {model: {'n': len(rows), 'correct': sum(r['correct_support_classification'] for r in rows),
             'paired_n': len(shared), 'paired_correct': sum(r['correct_support_classification'] for r in rows if r['id'] in shared),
             'per_case': rows} for model, rows in groups.items()}}
    for module in ('atomic', 'v2', 'selfcheck', 'triad'):
        rows = read(root / ('pilot_' + module) / 'predictions.jsonl')
        result['modules'][module] = {'journal_cases': len(rows), 'per_case': []}
        for row in rows:
            value = row['result']
            if module == 'atomic':
                audit = {name: value.get(name, {}).get('status') for name in ('target_inventory', 'target_checks', 'explanation_inventory', 'explanation_checks', 'whole_target_control')}
                audit['mechanical_target_coverage'] = value['target_inventory'].get('coverage')
                audit['atoms'] = value['target_inventory'].get('atoms')
            elif module == 'v2':
                audit = {'native_facts': value['native_fact_count'], 'step1_issues': value['step1']['issues'],
                         'step3_issues': value['step3']['issues'], 'step4': value['step4']}
            elif module == 'selfcheck':
                audit = {'judge_content_present': sum(bool(s.get('content')) for s in value['judge_samples']),
                         'target_content_present': sum(bool(s.get('content')) for s in value['target_samples']),
                         'judge_http_statuses': [s.get('http_status') for s in value['judge_samples']],
                         'target_http_statuses': [s.get('http_status') for s in value['target_samples']],
                         'corrected_classification': 'SAMPLING_FAILED_NLI_NOT_EXECUTED'}
            else:
                audit = value
            result['modules'][module]['per_case'].append({'id': row['id'], **audit})
    if (root / 'selfcheck_recovery/result.json').exists():
        result['modules']['selfcheck_recovery'] = json.loads((root / 'selfcheck_recovery/result.json').read_text())
    write(root / 'mechanism_audit.json', result)
    print(json.dumps({'CCG': {k: v for k, v in result['modules']['CCG'].items() if k != 'per_case'},
        'native': {k: {a: b for a, b in v.items() if a != 'per_case'} for k, v in result['modules']['native_claims']['models'].items()}}))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--root', type=Path, required=True)
    run(p.parse_args().root)
