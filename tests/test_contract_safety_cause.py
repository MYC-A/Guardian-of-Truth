"""Cause metrics cannot admit provider failures or incomplete judgement contracts."""
import json

import pytest

from guardian_truth.repair import cause
from guardian_truth.verification.pipeline import packet_for


class CauseClient:
    def __init__(self, value, status=200, finish='stop'):
        self.value, self.status, self.finish, self.calls = value, status, finish, []

    def call(self, request, attempt=0, tag=''):
        self.calls.append(dict(request=request, attempt=attempt, tag=tag))
        return dict(content=json.dumps(self.value), transport={'status': self.status},
                    finish_reason=self.finish, key='cause-fixture')


def fixture():
    row = dict(prompt='⟦SYSTEM⟧\nNever write FORBIDDEN.', response='⟦ASSISTANT · ход 1⟧\nFORBIDDEN')
    packet = packet_for(row, 20000)
    assert packet and packet['current_targets']
    accusation = dict(origin='review', target_id=packet['current_targets'][0]['source_id'], text='Forbidden word written.')
    value = dict(accusation_supported='yes', core_matches_gold='yes', unsupported_extra='no',
                 gold_supported='yes', rationale='The current assertion contains the forbidden word.',
                 category='supported_correct_core')
    return row, accusation, value


@pytest.mark.parametrize('judge', [cause.judge, cause.judge_v2])
@pytest.mark.parametrize('status,finish', [(429, 'stop'), (200, 'error')])
def test_failed_judge_receipt_is_technical_unjudged_even_with_valid_complete_body(judge, status, finish):
    row, accusation, value = fixture()
    client = CauseClient(value, status, finish)
    result = judge(client, 'test', row, accusation, ['Forbidden word written.'])
    assert result['category'] == 'technical_unjudged'
    assert result['why'] == 'TRANSPORT_FAILURE'
    assert result['transport'] == status and result['finish_reason'] == finish
    assert result['raw_content'] == json.dumps(value)
    assert len(client.calls) == 1


@pytest.mark.parametrize('judge', [cause.judge, cause.judge_v2])
@pytest.mark.parametrize('transport', [{'status': 403}, 'bad', [1], 3])
def test_malformed_transport_metadata_is_a_technical_failure_not_an_exception(judge, transport):
    row, accusation, value = fixture()
    client = CauseClient(value)
    original_call = client.call
    def reply(request, attempt=0, tag=''):
        return dict(original_call(request, attempt=attempt, tag=tag), transport=transport)
    client.call = reply
    result = judge(client, 'test', row, accusation, ['Forbidden word written.'])
    assert result['category'] == 'technical_unjudged'
    assert result['why'] == 'TRANSPORT_FAILURE'
    assert result['raw_content'] == json.dumps(value)
    assert result['transport'] == (transport['status'] if isinstance(transport, dict) else transport)


@pytest.mark.parametrize('judge', [cause.judge, cause.judge_v2])
@pytest.mark.parametrize('finish', ['stop', 'length'])
def test_complete_successful_judge_contract_is_accepted_without_wire_changes(judge, finish):
    row, accusation, value = fixture()
    client = CauseClient(value, finish=finish)
    result = judge(client, 'test', row, accusation, ['Forbidden word written.'])
    assert result['category'] == 'supported_correct_core'
    assert result['schema_validation']['status'] == 'VALID'
    assert client.calls[0]['request']['response_format'] == {'type': 'json_object'}
    builder = cause.judge_request if judge is cause.judge else cause.judge_request_v2
    assert client.calls[0]['request'] == builder('test', row, accusation, ['Forbidden word written.'])


@pytest.mark.parametrize('judge', [cause.judge, cause.judge_v2])
@pytest.mark.parametrize('field', list(cause.FIELDS) + ['rationale', 'category'])
def test_all_requested_judge_fields_are_required_locally(judge, field):
    row, accusation, value = fixture()
    value.pop(field)
    result = judge(CauseClient(value), 'test', row, accusation, ['Forbidden word written.'])
    assert result['category'] == 'technical_unjudged'
    assert result['schema_validation']['status'] == 'INVALID_SCHEMA'
    assert result['schema_validation']['errors']


@pytest.mark.parametrize('judge', [cause.judge, cause.judge_v2])
@pytest.mark.parametrize('mutation', [
    {'accusation_supported': True}, {'core_matches_gold': 'maybe'}, {'unsupported_extra': ['no']},
    {'gold_supported': 'unknown'}, {'rationale': None}, {'category': 'SAME'}, {'extra': 'not requested'},
])
def test_judge_types_enums_and_extra_fields_are_checked(judge, mutation):
    row, accusation, value = fixture()
    result = judge(CauseClient(dict(value, **mutation)), 'test', row, accusation, ['Forbidden word written.'])
    assert result['category'] == 'technical_unjudged'
    assert result['why'] == 'INVALID_SCHEMA'


def test_v2_complete_crossfield_contradiction_keeps_existing_invariant_contract():
    row, accusation, value = fixture()
    value['accusation_supported'] = 'no'
    result = cause.judge_v2(CauseClient(value), 'test', row, accusation, ['Forbidden word written.'])
    assert result['category'] == 'inconsistent_unjudged'
    assert result['raw_category'] == 'supported_correct_core'
    assert result['invariant'] == 'CATEGORY_CONTRADICTS_FIELDS:supported_correct_core'
    assert result['schema_validation']['status'] == 'VALID'
    # v1 receives the new required-field schema but is not retroactively assigned
    # v2's separate cross-field semantics or a revised gold policy.
    assert cause.judge(CauseClient(value), 'test', row, accusation, ['Forbidden word written.'])['category'] == 'supported_correct_core'
