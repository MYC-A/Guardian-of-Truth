import json
import pytest
from guardian_truth.source_search.store import SourceStore
from guardian_truth.action_audit import evaluate_audit, input_context
from guardian_truth.action_audit.evaluate import fact_source
from guardian_truth.policy_table.segment import clauses


def make(response='→ TOOL_CALL tool_a: {"field_n":99}', user='Please act for X.', extra=''):
    return SourceStore({'prompt': '⟦SYSTEM⟧\nTry tool_b before declining.\n[AVAILABLE TOOLS]\n'
        '- tool_a — apply\n    field_n: number!\n    field_s: string\n- tool_b — inspect\n    field_x: string!\n'
        '⟦USER⟧\n' + user + '\n⟦ASSISTANT⟧\n' + extra, 'response': response})


def argument(derivation='NONE', source='NONE', **changes):
    return {'target_source_id': 't0', 'argument': 'field_n', 'value_source_id': source, 'derivation': derivation, **changes}


def audit(args=(), acts=()): return {'arguments': list(args), 'text_acts': list(acts)}


def event(store, kind, role=None):
    return next(sid for sid, s in store.sources.items() if s['document'] == 'prompt' and s['kind'] == kind and (role is None or s['role'] == role))


def request(sid, **changes):
    return {'target_source_id': 't0', 'act': 'ASK_CLARIFY', 'performer': 'USER', 'asked_field': 'field_y',
        'asked_value': 7, 'already_known_at': sid, 'known_path': '/field_y', 'entity_arguments': {'field_x': 'X'}, **changes}


def test_absent_nonfree_argument_and_free_string_exemption():
    store = make(); result = evaluate_audit(store, audit([argument()]))
    assert len(result['findings']) == 1 and result['changes_judge_vote'] is False
    free = make('→ TOOL_CALL tool_a: {"field_s":"a new narrative"}')
    assert not evaluate_audit(free, audit([argument(argument='field_s')]))['findings']
    found = make(user='Use 99 for X.')
    assert not evaluate_audit(found, audit([argument()]))['findings']


def test_incomplete_or_duplicate_audit_never_downgrades_the_judge():
    store = make()
    for value in ({}, audit(), audit([argument(), argument()])):
        result = evaluate_audit(store, value)
        assert result['status'] == 'INVALID_AUDIT' and result['findings'] == []
        assert result['changes_judge_vote'] is False


def test_agent_rationale_is_not_independent_evidence():
    store = make(extra='I checked and found 99.')
    sid = event(store, 'text', 'assistant')
    result = evaluate_audit(store, audit([argument('COPIED', sid)]))
    assert result['trace'][0]['source_value_verified'] is False
    assert result['findings'] == []


def test_result_requestor_role_is_not_mistaken_for_result_speaker():
    store = make(extra='⟦TOOL_RESULT name="tool_b" requestor="assistant"⟧\n{"field_n":99}')
    sid = event(store, 'result')
    assert store.sources[sid]['role'] == 'assistant' and fact_source(store, sid)
    assert evaluate_audit(store, audit([argument('COPIED', sid)]))['trace'][0]['source_value_verified'] is True


def test_user_stated_rejects_a_tool_observation_and_accepts_user_source():
    store = make(user='Use 99.', extra='← TOOL_RESPONSE tool_b: {"field_n":99}')
    observed = event(store, 'result'); user = event(store, 'text', 'user')
    assert not evaluate_audit(store, audit([argument('USER_STATED', observed)]))['trace'][0]['source_value_verified']
    assert evaluate_audit(store, audit([argument('USER_STATED', user)]))['trace'][0]['source_value_verified']


def test_sourced_arithmetic_is_checked_and_invalid_operands_do_not_create_error():
    store = make('→ TOOL_CALL tool_a: {"field_n":5}', user='The values are 2 and 3.')
    user = event(store, 'text', 'user')
    arg = argument('COMPUTED', operation='sum', operands=[{'source_id': user, 'value': 2}, {'source_id': user, 'value': 3}])
    result = evaluate_audit(store, audit([arg]))
    assert result['trace'][0]['calculation']['matches_argument'] is True and not result['findings']
    arg['operands'][0]['value'] = 4
    assert evaluate_audit(store, audit([arg]))['trace'][0]['calculation']['status'] == 'UNKNOWN'


def test_known_answer_requires_the_same_entity_and_field():
    store = make('What is field_y for X?', extra='← TOOL_RESPONSE tool_b: {"field_x":"X","field_y":7}')
    sid = event(store, 'result')
    result = evaluate_audit(store, audit(acts=[request(sid)]))
    assert len(result['findings']) == 1
    assert result['findings'][0]['fact']['semantic_frame_proven_by_code'] is False
    for changes in ({'entity_arguments': {'field_x': 'Y'}}, {'asked_field': 'field_n'}, {'asked_value': 8}, {'entity_arguments': {}}):
        assert not evaluate_audit(store, audit(acts=[request(sid, **changes)]))['findings']


def test_ambiguous_records_nulls_and_newer_observation_are_not_known_answers():
    for extra in ('← TOOL_RESPONSE tool_b: {"field_x":"X","field_y":null}',
                  '← TOOL_RESPONSE tool_b: [{"field_x":"X","field_y":7},{"field_x":"X","field_y":7}]',
                  '← TOOL_RESPONSE tool_b: {"field_x":"X","field_y":7}\n← TOOL_RESPONSE tool_b: {"field_x":"X"}'):
        store = make('What is field_y for X?', extra=extra); sid = event(store, 'result')
        path = '/*/field_y' if '[' in store.history_events[store.sources[sid]['event']].text else '/field_y'
        assert not evaluate_audit(store, audit(acts=[request(sid, known_path=path)]))['findings']


def test_latest_user_typed_answer_can_be_checked_without_borrowing_old_entities():
    store = make('What is field_y?', user='{"field_y":7}')
    sid = event(store, 'text', 'user')
    result = evaluate_audit(store, audit(acts=[request(sid, entity_arguments={})]))
    assert len(result['findings']) == 1


def test_untried_step_is_only_a_candidate_and_claims_of_attempt_are_not_native_calls():
    store = make('I cannot help X.', extra='I already followed that step.')
    item = {'target_source_id': 't0', 'act': 'REFUSE', 'performer': 'ASSISTANT',
        'permitted_steps': [{'clause_id': clauses(store)[0]['id'], 'tool': 'tool_b', 'attempted_in_history': 'NONE'}]}
    result = evaluate_audit(store, audit(acts=[item]))
    assert len(result['candidates']) == 1 and result['findings'] == []
    result = evaluate_audit(store, audit(acts=[item]), judge_findings=[{'target_source_id': 't0', 'evidence_ids': [clauses(store)[0]['id']]}])
    assert result['findings'][0]['status'] == 'CONFIRMED_BY_JUDGE_OR_TABLE'


def test_false_absence_of_prior_attempt_and_wrong_target_actor_are_rejected():
    store = make('I cannot help X.', extra='→ TOOL_CALL tool_b: {"field_x":"X"}')
    item = {'target_source_id': 't0', 'act': 'REFUSE', 'performer': 'ASSISTANT',
        'permitted_steps': [{'clause_id': clauses(store)[0]['id'], 'tool': 'tool_b', 'attempted_in_history': 'NONE'}]}
    assert not evaluate_audit(store, audit(acts=[item]))['candidates']
    asked = make('What is field_y for X?', extra='← TOOL_RESPONSE tool_b: {"field_x":"X","field_y":7}')
    assert not evaluate_audit(asked, audit(acts=[request(event(asked, 'result'), performer='ASSISTANT')]))['findings']


def test_context_contains_only_input_bound_catalog_clauses_and_sources():
    store = make(); context = input_context(store)
    assert len(context['native_arguments']) == 1 and context['policy_clauses']
    assert all(sid in store.sources for sid in context['fact_sources'])


def test_native_transfer_annotation_stays_an_attempt_candidate_not_a_text_act():
    store = make(); value = audit([argument()])
    value['native_transfer_steps'] = [{'target_source_id': 't0', 'permitted_steps': [
        {'clause_id': clauses(store)[0]['id'], 'tool': 'tool_b', 'attempted_in_history': 'NONE'}]}]
    result = evaluate_audit(store, value)
    assert len(result['candidates']) == 1 and result['target_acts'] == []
    assert not any(f['type'] == 'ACTION_AUDIT_UNTRIED_STEP' for f in result['findings'])
