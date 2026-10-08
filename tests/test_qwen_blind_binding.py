"""Anti-anchoring and typed source-address contrasts through the production parser."""
import copy
import json

import pytest

from experiments.guardian_binding import blind
from guardian_truth.verification.common import schema_errors
from guardian_truth.verification.pipeline import packet_for


POLICY = 'Select the record belonging to the person the user requested.'
CATALOG = '''[AVAILABLE TOOLS]
- inspect_selected — Inspect a selected record.
    selection: object! — The selected record and options.
- list_records — Return available records.
'''


def packet(used='HIDDEN-VALUE', expected='R42', *, current_prose='SECRET CURRENT PROSE', extra_current=None):
    history = ('⟦USER⟧\nInspect the record belonging to Mira.\n⟦ASSISTANT · ход 0⟧\n'
               '→ TOOL_CALL list_records: {}\n← TOOL_RESPONSE list_records: ' +
               json.dumps({'records': [{'name': 'Mira', 'reference': expected}], 'ok': True}))
    prompt = '⟦SYSTEM⟧\n' + POLICY + '\n' + CATALOG + '\n' + history
    response = ('⟦ASSISTANT · ход 1⟧\n→ TOOL_CALL inspect_selected: ' +
                json.dumps({'selection': {'reference': used}}) + '\n' + current_prose)
    if extra_current:
        response += '\n' + extra_current
    p = packet_for(dict(prompt=prompt, response=response), 400000)
    assert p['coverage']['complete_input']
    return p


def proposal(p, *, path='/selection/reference', expected_pointer='/records/0/reference'):
    tid = next(x['source_id'] for x in p['current_targets'] if x['kind'] == 'call')
    result = next(x for x in p['history'] if x['kind'] == 'result')
    user = next(x for x in p['history'] if x['role'] == 'user')
    policy = next(x for x in p['normative_sources'] if POLICY in x['text'])
    return dict(target_id=tid, argument_path=path, expected_source_id=result['source_id'],
                expected_json_pointer=expected_pointer, request_source_id=user['source_id'],
                request_quote='Inspect the record belonging to Mira.', policy_source_id=policy['source_id'],
                policy_quote=POLICY, rationale='The returned record is the requested one.', status='ESTABLISHED')


def admit(p, item=None):
    return blind.admit({'bindings': [item or proposal(p)]}, p)


def test_blind_request_is_invariant_to_used_values_and_current_prose():
    a, b = packet('HIDDEN-ONE', current_prose='PRIVATE PROSE ONE'), packet('HIDDEN-TWO', current_prose='PRIVATE PROSE TWO')
    req = blind.construct_request(a, 'qwen')
    assert req == blind.construct_request(b, 'qwen')
    serialized = json.dumps(req)
    for secret in ('HIDDEN-ONE', 'HIDDEN-TWO', 'PRIVATE PROSE ONE', 'PRIVATE PROSE TWO', 'current_targets'):
        assert secret not in serialized
    assert req['temperature'] == 0 and req['max_tokens'] == 1700
    assert req['chat_template_kwargs']['enable_thinking'] is False


def test_blind_drops_current_metadata_but_history_change_changes_request():
    a = packet()
    b = copy.deepcopy(a)
    b['coverage']['declaration_status'] = {'HIDDEN-VALUE': 'LEAK'}
    b['coverage']['unread'] = [{'category': 'HISTORY', 'reason': 'HIDDEN-VALUE', 'unread_units': 1}]
    a['coverage']['unread'] = [{'category': 'HISTORY', 'reason': 'OTHER', 'unread_units': 1}]
    b['debug_current_response'] = 'HIDDEN-VALUE'
    assert blind.construct_request(a, 'qwen') == blind.construct_request(b, 'qwen')
    changed = packet(expected='R99')
    assert blind.construct_request(a, 'qwen') != blind.construct_request(changed, 'qwen')


def test_historical_coincidence_is_not_scrubbed_and_visible_control_shows_used_value():
    p = packet('R42', expected='R42')
    assert 'R42' in blind.construct_request(p, 'qwen')['messages'][1]['content']
    p = packet('HIDDEN-VALUE')
    assert 'HIDDEN-VALUE' not in blind.construct_request(p, 'qwen')['messages'][1]['content']
    assert 'HIDDEN-VALUE' in blind.construct_request(p, 'qwen', 'visible')['messages'][1]['content']


def test_source_addressed_mismatch_is_never_a_violation_certificate():
    p = packet('OTHER-RECORD')
    result = admit(p)
    assert result['admission'] == 'PROCESSED'
    assert len(result['mismatch_candidates']) == 1
    candidate = result['mismatch_candidates'][0]
    assert candidate['authority'] == 'SOURCE_SUPPORTED_ONLY'
    assert candidate['binding_status'] == candidate['applicability_status'] == 'UNRESOLVED'
    assert candidate['final_authority'] == 'NONE' and not candidate['certificate']
    assert candidate['used']['value'] == 'OTHER-RECORD' and candidate['expected']['value'] == 'R42'
    assert 'binary' not in result and 'ERROR' not in result.values()


@pytest.mark.parametrize('used,expected,match', [
    ('42', 42, False), (True, 1, False), (False, 0, False),
    (None, None, True), (42, 42.0, True), ('R42', 'R42', True), ('r42', 'R42', False),
])
def test_comparison_has_json_types_and_no_string_or_boolean_numeric_coercion(used, expected, match):
    p = packet(used, expected)
    result = admit(p)
    assert bool(result['mismatch_candidates']) is not match
    assert result['records'][0]['comparison'] == ('MATCH' if match else 'MISMATCH')


def test_numbers_do_not_round_through_float():
    p = packet(1, 2)
    current = next(x for x in p['current_targets'] if x['kind'] == 'call')
    current['text'] = current['text'].replace('"reference": 1', '"reference": 9007199254740993.0')
    source = next(x for x in p['history'] if x['kind'] == 'result')
    source['text'] = source['text'].replace('"reference": 2', '"reference": 9007199254740992.0')
    result = admit(p)
    assert result['mismatch_candidates'][0]['expected']['value'] == '9007199254740992.0'
    assert result['mismatch_candidates'][0]['used']['value'] == '9007199254740993.0'


@pytest.mark.parametrize('pointer', ['/records/-1/reference', '/records/00/reference', '/records/0/~2bad',
                                     'records/0/reference', '/records/0', '/missing'])
def test_invalid_noncanonical_or_container_pointer_is_not_resolved(pointer):
    p = packet()
    result = admit(p, proposal(p, expected_pointer=pointer))
    assert not result['mismatch_candidates']
    assert result['records'][0]['admission'] == 'UNRESOLVED_EXPECTATION'


def test_escaped_rfc6901_keys_are_exact():
    p = packet()
    source = next(x for x in p['history'] if x['kind'] == 'result')
    source['text'] = '← TOOL_RESPONSE list_records: {"a/b":{"~key":"R42"}}'
    result = admit(p, proposal(p, expected_pointer='/a~1b/~0key'))
    assert result['records'][0]['expected']['value'] == 'R42'


@pytest.mark.parametrize('raw', [
    '{"records":[{"reference":"R42","reference":"OTHER"}]}',
    '{"records":[{"reference":NaN}]}',
    '{"records":[{"reference":"R42"}]} trailing content',
    '{"ok":false,"records":[{"reference":"R42"}]}',
    '{"status":"failed","records":[{"reference":"R42"}]}',
])
def test_ambiguous_nonfinite_trailing_or_failed_source_cannot_establish_value(raw):
    p = packet()
    source = next(x for x in p['history'] if x['kind'] == 'result')
    source['text'] = '← TOOL_RESPONSE list_records: ' + raw
    result = admit(p)
    assert not result['mismatch_candidates']
    assert result['records'][0]['admission'] == 'UNRESOLVED_EXPECTATION'


def test_invalid_current_json_creates_no_hidden_value_inventory():
    p = packet()
    target = next(x for x in p['current_targets'] if x['kind'] == 'call')
    target['text'] = '→ TOOL_CALL inspect_selected: {"reference":"SECRET","reference":"OTHER"}'
    req = blind.construct_request(p, 'qwen')
    user = json.loads(req['messages'][1]['content'])
    assert not user['current_actions'] and user['current_gaps']
    assert 'SECRET' not in req['messages'][1]['content']
    assert not schema_errors({'bindings': []}, req['response_format']['json_schema']['schema'])


@pytest.mark.parametrize('key,value', [('request_quote', 'Invented request'), ('policy_quote', 'Invented policy'),
                                      ('request_source_id', 'invented-source'), ('expected_source_id', 't0'),
                                      ('argument_path', '/not-a-real-path')])
def test_cited_ids_quotes_and_current_paths_cannot_be_invented(key, value):
    p = packet()
    item = dict(proposal(p), **{key: value})
    result = admit(p, item)
    assert not result['mismatch_candidates']


def test_duplicate_assessments_are_quarantined_and_missing_paths_explicit():
    p = packet()
    item = proposal(p)
    result = blind.admit({'bindings': [item, item]}, p)
    # maxItems rejects excess rows rather than selecting a convenient duplicate.
    assert result['admission'] == 'REJECTED_SCHEMA'
    assert not result['mismatch_candidates']
    missing = blind.admit({'bindings': []}, p)
    assert not missing['coverage']['complete'] and missing['coverage']['unchecked']


@pytest.mark.parametrize('status', ['LAWFUL_CHOICE', 'UNRESOLVED'])
def test_nonunique_or_unknown_expectation_never_forces_mismatch(status):
    p = packet()
    item = dict(proposal(p), status=status, expected_source_id=None, expected_json_pointer=None,
                request_source_id=None, request_quote=None, policy_source_id=None, policy_quote=None)
    result = admit(p, item)
    assert result['records'][0]['admission'] == 'RETAINED_HYPOTHESIS'
    assert not result['mismatch_candidates']


def test_exact_quote_with_removed_not_is_rejected():
    p = packet()
    user = next(x for x in p['history'] if x['role'] == 'user')
    user['text'] = 'Do NOT inspect the record belonging to Mira.'
    item = dict(proposal(p), request_quote='Do inspect the record belonging to Mira.')
    assert admit(p, item)['records'][0]['admission'] == 'REJECTED_SOURCE_QUOTE'


def test_missing_original_current_values_in_reply_cannot_be_filled_by_model():
    p = packet()
    item = dict(proposal(p), used_value='model-invented')
    assert admit(p, item)['admission'] == 'REJECTED_SCHEMA'


def test_duplicate_source_id_is_explicit_configuration_error():
    p = packet()
    p['history'].append(copy.deepcopy(p['history'][0]))
    with pytest.raises(ValueError, match='DUPLICATED_SOURCE_ID'):
        blind.construct_request(p, 'qwen')
