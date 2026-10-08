"""Compact-output controls retain v1 source visibility and typed admission."""
import copy
import json

import pytest

from experiments.guardian_binding import blind, blind_compact as compact
from guardian_truth.verification.pipeline import packet_for


def packet(used='HIDDEN-ARG', expected='R42', prose='HIDDEN PROSE'):
    prompt = ('⟦SYSTEM⟧\nSelect the requested record.\n[AVAILABLE TOOLS]\n'
              '- inspect — Inspect a record.\n    reference: string! — Record reference.\n'
              '- list_records — Return records.\n⟦USER⟧\nInspect Mira.\n⟦ASSISTANT · ход 0⟧\n'
              '→ TOOL_CALL list_records: {}\n← TOOL_RESPONSE list_records: ' +
              json.dumps({'records': [{'owner': 'Mira', 'reference': expected}]}))
    response = '⟦ASSISTANT · ход 1⟧\n→ TOOL_CALL inspect: ' + json.dumps({'reference': used}) + '\n' + prose
    p = packet_for({'prompt': prompt, 'response': response}, 400000)
    assert p['coverage']['complete_input']
    return p


def binding(p):
    return dict(t=next(x['source_id'] for x in p['current_targets'] if x['kind'] == 'call'), a='/reference',
                s=next(x['source_id'] for x in p['history'] if x['kind'] == 'result'), p='/records/0/reference',
                r=next(x['source_id'] for x in p['history'] if x['role'] == 'user'), v='E')


def test_compact_keeps_exact_v1_visibility_and_reduces_only_output_wire():
    p = packet()
    for mode in compact.MODES:
        a, b = blind.construct_request(p, 'qwen', mode), compact.construct_request(p, 'qwen', mode)
        assert a['messages'][1] == b['messages'][1]
        assert b['max_tokens'] == 900 and b['temperature'] == 0
        assert b['chat_template_kwargs'] == {'enable_thinking': False}
        assert set(b['response_format']['json_schema']['schema']['properties']['bindings']['items']['properties']) == set('tasprv')


def test_blind_invariance_and_visible_intervention():
    a, b = packet('HIDDEN-ONE', prose='PRIVATE-ONE'), packet('HIDDEN-TWO', prose='PRIVATE-TWO')
    assert compact.construct_request(a, 'qwen') == compact.construct_request(b, 'qwen')
    text = json.dumps(compact.construct_request(a, 'qwen'))
    assert 'HIDDEN-ONE' not in text and 'PRIVATE-ONE' not in text
    assert 'HIDDEN-ONE' in json.dumps(compact.construct_request(a, 'qwen', 'visible'))
    assert compact.construct_request(a, 'qwen') != compact.construct_request(packet(expected='R99'), 'qwen')


def test_code_owned_request_quote_is_not_model_binding_proof():
    p = packet()
    result = compact.admit({'bindings': [binding(p)]}, p)
    candidate = result['mismatch_candidates'][0]
    assert result['request_quote_origin'] == candidate['request_quote_origin'] == 'CODE_SOURCE_TEXT'
    user = next(x for x in p['history'] if x['role'] == 'user')
    assert candidate['request_quote'] == user['text']
    assert candidate['authority'] == 'SOURCE_SUPPORTED_ONLY'
    assert candidate['binding_authority'] == 'MODEL_HYPOTHESIS'
    assert candidate['binding_status'] == candidate['applicability_status'] == 'UNRESOLVED'
    assert not candidate['certificate'] and candidate['final_authority'] == 'NONE'
    assert candidate['policy_source_id'] is None and candidate['policy_quote'] is None
    assert 'binary' not in result


@pytest.mark.parametrize('v', ['L', 'U'])
def test_choice_or_unknown_cannot_make_mismatch(v):
    p = packet()
    item = dict(binding(p), v=v, s=None, p=None, r=None)
    result = compact.admit({'bindings': [item]}, p)
    assert not result['mismatch_candidates']
    assert result['records'][0]['admission'] == 'RETAINED_HYPOTHESIS'


@pytest.mark.parametrize('mutation', [
    lambda x: dict(x, v='MISMATCH'), lambda x: dict(x, rationale='extra'),
    lambda x: {k: v for k, v in x.items() if k != 'v'}, lambda x: dict(x, a='/invented'),
    lambda x: dict(x, r='invented-source'), lambda x: dict(x, s='t0'),
])
def test_malformed_schema_or_addresses_never_invent_status(mutation):
    p = packet()
    result = compact.admit({'bindings': [mutation(binding(p))]}, p)
    assert result['admission'] == 'REJECTED_SCHEMA' and not result['mismatch_candidates']


@pytest.mark.parametrize('raw', ['{"bindings":[', '{"bindings":[],"bindings":[]}', 'null'])
def test_invalid_or_duplicate_json_is_rejected(raw):
    result = compact.admit(raw, packet())
    assert result['admission'] == 'REJECTED_SCHEMA'


def test_request_source_must_be_actual_user_text_not_assistant_summary():
    p = packet()
    item = binding(p)
    item['r'] = next(x['source_id'] for x in p['history'] if x['role'] == 'assistant')
    assert compact.admit({'bindings': [item]}, p)['admission'] == 'REJECTED_SCHEMA'


@pytest.mark.parametrize('pointer', ['/records/-1/reference', '/records/00/reference', '/records/0'])
def test_invalid_or_container_pointer_remains_unresolved(pointer):
    p = packet()
    result = compact.admit({'bindings': [dict(binding(p), p=pointer)]}, p)
    assert not result['mismatch_candidates']
    assert result['records'][0]['admission'] == 'UNRESOLVED_EXPECTATION'


def test_precision_preserved_without_generating_numeric_values_in_reply():
    p = packet(1, 2)
    current = next(x for x in p['current_targets'] if x['kind'] == 'call')
    current['text'] = current['text'].replace('"reference": 1', '"reference": 9007199254740993.0')
    source = next(x for x in p['history'] if x['kind'] == 'result')
    source['text'] = source['text'].replace('"reference": 2', '"reference": 9007199254740992.0')
    result = compact.admit(json.dumps({'bindings': [binding(p)]}), p)
    assert result['mismatch_candidates'][0]['used']['value'] == '9007199254740993.0'
    assert result['mismatch_candidates'][0]['expected']['value'] == '9007199254740992.0'


def test_same_value_is_match_and_missing_assessment_visible():
    p = packet('R42', 'R42')
    result = compact.admit({'bindings': [binding(p)]}, p)
    assert result['records'][0]['comparison'] == 'MATCH' and not result['mismatch_candidates']
    missing = compact.admit({'bindings': []}, p)
    assert not missing['coverage']['complete'] and missing['coverage']['unchecked']
