from copy import deepcopy
import json
from pathlib import Path

import pytest

from guardian_truth.vnext.semantic import Proposal
from guardian_truth.vnext.stage_tool_t2_v1 import predict_t2, score_t2, summarize_t2
from guardian_truth.vnext.types import EffectStatus


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = json.loads((ROOT / 'benchmarks/vnext/tool_semantics_v1.json').read_text(encoding='utf-8'))
REFERENCE = (ROOT / 'benchmarks/vnext/tool_reference_v1.py').read_text(encoding='utf-8')


class Backend:
    def __init__(self, *, effects=None, transport_error=False, schema_error=False):
        self.effects = effects if effects is not None else [{'argument_entity_field': 'record_id',
            'predicate': 'archived', 'value_json': 'true', 'result_grounding_fields': ['status']}]
        self.transport_error, self.schema_error = transport_error, schema_error
        self.payloads = []

    def propose(self, task, payload, schema):
        self.payloads.append(payload)
        if self.transport_error:
            return Proposal(None, 'ERROR', 'NOT_EVALUATED', 'timeout')
        if self.schema_error:
            return Proposal('{}', 'SUCCESS', 'INVALID')
        return Proposal(json.dumps({'hypotheses': self.effects}), 'SUCCESS', 'VALID')


@pytest.mark.parametrize('case', BENCHMARK['cases'], ids=lambda case: case['case_id'])
def test_every_t2_fixture_candidate_stays_untrusted_and_outside_ledger(case):
    backend = Backend()
    prediction = predict_t2(case['input'], backend, REFERENCE)
    effects = prediction['semantics']['effects']
    assert len(effects) == 1
    assert effects[0]['status'] is EffectStatus.POSSIBLE_EFFECT
    assert effects[0]['contract_sha256'] is None
    assert effects[0]['causal_action_confirmed'] is False
    assert prediction['ledger_effects_before'] == prediction['ledger_effects_after'] == 0
    assert 'gold' not in backend.payloads[0]
    assert case['input']['arguments'] == backend.payloads[0]['arguments']
    score = score_t2(case, prediction)
    assert score['unsafe_trusted_candidates'] == 0
    assert len(prediction['candidate_primitive_proofs']) == 3
    assert all(proof['value'] == 'UNKNOWN' for proof in prediction['candidate_primitive_proofs'])
    assert score['false_state_action_causal_support'] == 0
    if case['gold']['archived'] is None:
        assert score['unknown_reference_candidates_unadjudicated'] == 1


def test_t2_grounding_rejections_preserve_raw_candidate_for_audit():
    case = BENCHMARK['cases'][0]
    effect = {'argument_entity_field': 'record_id', 'predicate': 'archived',
        'value_json': 'true', 'result_grounding_fields': ['invented_field']}
    prediction = predict_t2(case['input'], Backend(effects=[effect]), REFERENCE)
    assert not prediction['semantics']['effects']
    assert json.loads(prediction['raw_proposals'][0]['payload_json'])['hypotheses'] == [effect]
    score = score_t2(case, prediction)
    assert score['raw_candidates'] == score['grounding_rejections'] == 1


@pytest.mark.parametrize('failure', ['transport_error', 'schema_error'])
def test_t2_component_failures_are_excluded_not_semantic_false_negatives(failure):
    case = BENCHMARK['cases'][0]
    prediction = predict_t2(case['input'], Backend(**{failure: True}), REFERENCE)
    report = summarize_t2([case], [{'case_id': case['case_id'], 'prediction': prediction}])
    assert report['known_true_candidate_recall']['eligible'] == 0
    assert report['known_true_candidate_recall']['rate'] is None
    assert report['known_true_candidate_recall']['excluded_transport_schema'] == 1


def test_t2_ambiguity_keeps_both_states_without_voting_or_fact_promotion():
    case = BENCHMARK['cases'][0]
    effects = Backend().effects
    effects.append({**effects[0], 'value_json': 'false'})
    prediction = predict_t2(case['input'], Backend(effects=effects), REFERENCE)
    assert prediction['semantics']['status'] is EffectStatus.AMBIGUOUS_EFFECT
    assert len(prediction['semantics']['effects']) == 2
    assert prediction['ledger_effects_after'] == 0


def test_t2_reference_precision_never_calls_unknown_states_false():
    cases = BENCHMARK['cases']
    rows = [{'case_id': case['case_id'], 'prediction': predict_t2(case['input'], Backend(), REFERENCE)} for case in cases]
    report = summarize_t2(cases, rows)
    assert report['known_true_candidate_recall']['rate'] == 1
    assert report['unsafe_trusted_effects']['count'] == 0
    assert report['full_candidate_precision'].startswith('NOT_ESTABLISHED')
    assert report['real_tool_generalization'] == report['downstream_gain'] == 'NOT_ESTABLISHED'
    assert any(score['version_incompatible_candidates_not_documentation_supported'] for score in report['failure_taxonomy'])


def test_t2_audit_detects_tampered_trusted_candidate_and_ledger_pollution():
    case = BENCHMARK['cases'][0]
    prediction = deepcopy(predict_t2(case['input'], Backend(), REFERENCE))
    prediction['semantics']['effects'][0]['status'] = 'TRUSTED_EFFECT'
    prediction['ledger_effects_after'] = 1
    score = score_t2(case, prediction)
    assert score['unsafe_trusted_candidates'] == 1
    assert score['ledger_pollution'] is True
