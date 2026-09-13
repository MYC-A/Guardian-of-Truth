from dataclasses import asdict
import json
from pathlib import Path

import pytest

from guardian_truth.cycle2.policy_arms import BlindPolicyCase, arm_messages, load_policy_arm_contract
from guardian_truth.cycle2.policy_semantics import PolicyCase, PolicyWorld
from guardian_truth.llm_client import Completion
from guardian_truth.vnext.stage_policy_programs_v1 import predict_policy_programs, score_program_case, summarize_programs
from test_vnext_policy_programs_v2 import ATOMS, Backend, IF, ONLY_IF, POLICY, reading


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = load_policy_arm_contract(ROOT / 'contracts/cycle2_policy_arms_v1.json')
CASE = PolicyCase('controlled', 'only_if', 'minimal', 'controlled', 'source', POLICY, ATOMS,
    {}, {name: tuple(tuple(clause) for clause in clauses) for name, clauses in ONLY_IF.as_json().items()},
    (PolicyWorld('unapproved_attempt', ('ACT',), 'VIOLATION', 'only_if_direction'),
     PolicyWorld('approved_attempt', ('ACT', 'APPROVED'), 'NO_VIOLATION', 'only_if_direction')))
BLIND = BlindPolicyCase(CASE.id, CASE.family, CASE.variant, CASE.policy, CASE.atom_catalog)


class Wire:
    def __init__(self):
        self.calls = []

    def complete(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return Completion(json.dumps({'case_id': CASE.id, **ONLY_IF.as_json()}), {}, 'controlled')


def prediction(*, challenger=None, failure=None):
    return predict_policy_programs(BLIND, Backend(challenger=challenger, failure=failure), Wire(), CONTRACT)


def test_baseline_is_exact_original_p1_messages_schema_and_effort_not_p2():
    backend, wire = Backend(), Wire()
    result = predict_policy_programs(BLIND, backend, wire, CONTRACT)
    messages, schema = arm_messages(BLIND, 'P1', CONTRACT)
    assert wire.calls == [(messages, {'schema': schema, 'reasoning_effort': CONTRACT.reasoning_effort})]
    assert result['fixed_p1']['arm'] == 'P1'
    assert len(backend.tasks) == 2


def test_safe_input_view_has_no_gold_world_structure_or_program_fields():
    assert set(asdict(BLIND)) == {'id', 'family', 'variant', 'policy', 'atom_catalog'}
    assert not {'worlds', 'structure', 'program'} & set(asdict(BLIND))


def test_tuple_dataclass_and_json_roundtrip_score_identically():
    result = prediction()
    assert score_program_case(CASE, result) == score_program_case(CASE, json.loads(json.dumps(result)))
    assert score_program_case(CASE, result)['all_candidate_correct']


def test_challenger_wrong_behavior_is_retained_and_any_is_not_all():
    score = score_program_case(CASE, prediction(challenger=[reading(IF)]))
    assert score['candidate_count'] == 2
    assert score['candidate_correct'] == 1
    assert score['any_candidate_correct'] and not score['all_candidate_correct']
    assert 'POLICY_GENERATION' in score['components']


def test_transport_failure_excluded_from_conditional_paired_case_accuracy():
    result = prediction(failure='policy_program_missing_reading_v2')
    report = summarize_programs([CASE], [{'case_id': CASE.id, 'prediction': result}])
    assert report['candidate_behavior']['candidates'] == 1
    assert report['candidate_behavior']['full_case_eligible'] == report['paired']['n'] == 0
    assert report['candidate_behavior']['strict_operational_all_correct_yield'] == 0
    assert 'TRANSPORT' in report['failure_taxonomy'][0]['components']


def test_empty_candidates_do_not_vacuously_count_correct():
    result = predict_policy_programs(BLIND, Backend(initial=[]), Wire(), CONTRACT)
    score = score_program_case(CASE, result)
    assert not score['all_candidate_correct'] and not score['any_candidate_correct']
    assert score['coverage'] == 'OPEN_SEMANTICS'


def test_report_requires_all_unique_case_ids():
    row = {'case_id': CASE.id, 'prediction': prediction()}
    with pytest.raises(ValueError):
        summarize_programs([CASE], [row, row])
    with pytest.raises(ValueError):
        summarize_programs([CASE], [])
