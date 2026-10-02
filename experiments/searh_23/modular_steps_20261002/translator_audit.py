"""Separate semantic DEV audit of the fixed translator pilot, not tuning."""
from collections import Counter, defaultdict
import json
from pathlib import Path
from modular_common import write


def run(root):
    rows = [json.loads(s) for s in (root / 'translator_pilot/predictions.jsonl').read_text(encoding='utf-8').splitlines()]
    by = defaultdict(Counter)
    for r in rows:
        key = r['model']
        by[key]['attempted_cases'] += 1
        if r['raw'].get('http_status'):
            by[key]['http_' + str(r['raw']['http_status'])] += 1
        elif r['raw'].get('content'):
            by[key]['model_answers'] += 1
            status = r.get('format_status', 'VALID')
            by[key]['schema_' + status.lower()] += 1
            by[key][r['guarded_relation']] += 1
            by[key]['explicit_UNSUPPORTED'] += int(isinstance(r['translation'], dict) and r['translation'].get('status') == 'UNSUPPORTED')
    findings = [
        {'model': 'env_mistral', 'id': 'dev_implication::01',
         'classification': 'SEMANTIC_WRONG_DIRECTION_WITH_VALID_SCHEMA',
         'source': 'If a is true, verified is true.',
         'translation': 'ONLY_IF(conditions=[a], conclusion=verified)',
         'why': 'Original implies a -> verified. ONLY_IF representation means verified -> a; supported query is lost.'},
        {'model': 'env_mistral', 'id': 'dev_entity_binding::01',
         'classification': 'INVALID_QUOTE',
         'why': 'Invents right arrow TOOL_RESPONSE instead of the actual left arrow. Verbatim validator correctly rejects.'},
        {'model': 'mistral/codestral-2508', 'ids': ['dev_nested_gate::00', 'dev_nested_gate::01'],
         'classification': 'SEMANTIC_NON_EQUIVALENT_TWO_IFF_ALTERNATIVES',
         'why': 'Writes permitted <-> (a AND b), permitted <-> (a AND c). Together these are not permitted <-> (a AND (b OR c)).',
         'independent_counterexample': {'a': True, 'b': True, 'c': False, 'author_permission': True,
             'classical_two_IFF_formulas': 'UNSAT with these observed literals',
             'Horn_forward_closure': 'Can still derive permission; forward solver does not detect this semantic defect.'},
         'scope': 'Counterexample to parsed rule semantics, not a new measured binary row.'},
        {'model': 'mistral/codestral-2508', 'ids': ['dev_negative_scope::00', 'dev_negative_scope::01'],
         'classification': 'POLICY_OR_GOAL_AS_WORLD_FACT_PLUS_INVALID_RULE_QUOTE',
         'why': 'Asserts a=false and b=true using the requirement/Process item goal instead of observed b=false. Separate rule quote drops an intervening sentence. Source quote validity alone would not fix fabricated facts.'},
        {'model': 'mistral/codestral-2508', 'ids': ['dev_implication::01', 'dev_entity_binding::01'],
         'classification': 'SUPPORTED_QUERY_CORRECTLY_DERIVED',
         'why': 'Exact observed same-ID literal; IF direction correct in implication case. These two determined relations agree with independent author gold.'}
    ]
    report = {'scope': '8 paired DEV cases, original narrow signed-Horn IR; not a full-policy parser comparison',
              'models': {k: dict(v) for k, v in by.items()}, 'semantic_findings': findings,
              'selection': 'No challenger selected as trusted compiler; Codestral may provide independently checked advisory only.',
              'access_failures_are_not_quality_scores': True}
    write(root / 'translator_audit.json', report)
    print(json.dumps(report['models']))
    return report


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--root', required=True, type=Path)
    run(p.parse_args().root)
