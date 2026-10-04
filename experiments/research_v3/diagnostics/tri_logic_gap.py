"""Finite query-relevance audit of the unchanged three-valued requirement runtime.

Supplied Boolean interpretations only. This is not a policy extraction benchmark
and does not change original decisions or prove semantic completeness.
"""
from itertools import product
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'experiments/research_v3'))
from pilot import write
from guardian_truth.evidence_graph.logic import conjunction, negate, evaluate_requirement


def atom(label):
    return {'op': 'ATOM', 'label': label, 'spans': [], 'children': []}


def audit():
    rows = []
    for modality in ('REQUIRE', 'FORBID'):
        r = {'condition': atom('condition'), 'guard': atom('guard'),
             'exceptions': [atom('exception')], 'modality': modality, 'open_questions': []}
        for guard, condition, exemption in product(('TRUE', 'FALSE', 'UNKNOWN'), repeat=3):
            w = {path: {'value': value, 'reason': 'Supplied finite assignment'} for path, value in
                 [('guard', guard), ('condition', condition), ('exception.0', exemption)]}
            original = evaluate_requirement(r, w)['status']
            bad_condition = negate(condition) if modality == 'REQUIRE' else condition
            violation = conjunction([guard, negate(exemption), bad_condition])
            original_verdict = 'ERROR' if original == 'VIOLATED' else 'UNKNOWN' if original == 'UNKNOWN' else 'NO_ERROR'
            reference_verdict = {'TRUE': 'ERROR', 'FALSE': 'NO_ERROR', 'UNKNOWN': 'UNKNOWN'}[violation]
            if original_verdict != reference_verdict:
                rows.append({'modality': modality, 'guard': guard, 'condition': condition, 'exception': exemption,
                             'runtime_status': original, 'runtime_verdict': original_verdict,
                             'independent_violation_query': reference_verdict})
    return {'assignments': 54, 'differences': len(rows), 'rows': rows,
            'scope': 'ONE_SUPPLIED_NORM; NO_SEMANTIC_EXTRACTION; NOT_FULL_POLICY_NO_ERROR_PROOF',
            'hypothesis': 'An irrelevant unresolved guard/exception can inflate UNKNOWN even when violation is impossible.',
            'new_http': 0, 'runtime_changed': False}


if __name__ == '__main__':
    result = audit()
    write(ROOT / 'outputs/searh_23/semantic_hybrid_v4_diagnostics_20261004/tri_logic_gap.json', result)
    print(json.dumps(result))
