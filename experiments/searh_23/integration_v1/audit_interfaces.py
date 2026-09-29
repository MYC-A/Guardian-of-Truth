"""Replay frozen deterministic interface controls; no model calls."""
from __future__ import annotations

import json
import sys
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(HERE.parent / 'step1_working_v1')]
GUARDED = '--guard' in sys.argv
if GUARDED: os.environ['W1_SCOPE_GUARD'] = '1'

from w1_pipe3 import compatible_nodes
from guardian_truth.step2.types import EffectStrength
from guardian_truth.step2.verifier import (CallEvent, ResultEvent, TrajectoryCase,
                                         CandidateFact, VerifiedFact, verify_candidate)
from guardian_truth.step2.trusted import assess


def run():
    controls = json.loads((HERE / 'frozen/audit_controls.json').read_text(encoding='utf-8'))
    events = []
    for row in controls['event_pairs']:
        got = compatible_nodes([row['a']], [row['b']])
        events.append({**row, 'actual_compatible': got,
                       'passed': got == row['expected_compatible']})
    facts = []
    for row in controls['fact_controls']:
        call = CallEvent(0, 'c1', 'opaque_tool', {'unit_id': 'U-17'})
        payload = {'status': 'completed'}
        if not row.get('no_entity_echo'):
            payload['unit_id'] = 'U-17'
        result = ResultEvent(1, 'c1', row.get('result_tool', 'opaque_tool'), payload)
        case = TrajectoryCase('audit', 'interface', 'synthetic',
                              ({'name':'opaque_tool','description':'Reports a record field.'},),
                              (call,), (result,))
        candidate = CandidateFact(row['predicate'], 'unit', 'unit_id', 'U-17',
                                  row['value_json'], row['path'],
                                  EffectStrength(row['strength']),
                                  is_observation=row['is_observation'],
                                  contract_bound=row['contract_bound'])
        verdict = verify_candidate(case, call, result, candidate)
        accepted = isinstance(verdict, VerifiedFact)
        facts.append({**row, 'legacy_accepted': accepted,
                      'verdict': verdict.as_dict(),
                      'passed': accepted == row['expected_legacy_safe']})
        if GUARDED:
            guarded = assess(case,call,result,candidate)
            facts[-1]['guarded'] = guarded.as_dict()
    summary = {'event_compatibility_passed': sum(x['passed'] for x in events),
               'event_controls': len(events),
               'unsafe_fact_controls_accepted': sum(x['legacy_accepted'] and
                                                    not x['expected_legacy_safe'] for x in facts),
               'fact_controls': len(facts)}
    if GUARDED:
        summary['guarded_business_facts_established_without_contract'] = sum(
            bool(x['guarded']['verified']) for x in facts)
        summary['real_field_report_preserved'] = next(
            bool(x['guarded']['observation']) for x in facts if x['id']=='real_field_report')
    data = {'scope': 'development interface controls, not sealed generalization',
            'summary': summary, 'event_pairs': events, 'fact_controls': facts}
    dest = HERE / 'outputs'; dest.mkdir(exist_ok=True)
    name = 'guarded_interface_audit.json' if GUARDED else 'interface_audit.json'
    (dest / name).write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n',
                                             encoding='utf-8', newline='\n')
    print(json.dumps(summary))
    for row in events:
        if not row['passed']: print('UNSAFE_COMPATIBILITY', row['id'])
    for row in facts:
        if row['legacy_accepted'] and not row['expected_legacy_safe']:
            print('UNSAFE_FACT', row['id'])


if __name__ == '__main__':
    run()
