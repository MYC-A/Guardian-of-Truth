import copy
import json

import pytest

from experiments.guardian_binding import relational
from guardian_truth.verification.pipeline import packet_for


def packet(records=None):
    records = records if records is not None else [dict(criterion='555-2001', handle='A'), dict(criterion='555-2002', handle='B')]
    row = dict(prompt='⟦SYSTEM⟧\nAct on the requested record.\n⟦USER⟧\nUse the record ending in 2002.\n'
               '⟦ASSISTANT⟧\n→ TOOL_CALL scan: {}\n← TOOL_RESPONSE scan: ' + json.dumps(records) + '\n',
               response='⟦ASSISTANT⟧\n→ TOOL_CALL select: {"handle":"A"}')
    return packet_for(row, 400000)


def query(**changes):
    return dict(t='t0', a='/handle', r='h1', quote='Use the record ending in 2002.',
                field='criterion', op='SUFFIX', operand='2002', project='handle', status='Q', **changes)


def test_unique_native_same_object_relation_yields_only_unverified_mismatch():
    pk = packet(); before = copy.deepcopy(pk)
    result = relational.admit(json.dumps(dict(bindings=[query()])), pk)
    candidate = result['mismatch_candidates'][0]
    assert candidate['expected'] == {'type': 'STRING', 'value': 'B'}
    assert candidate['used'] == {'type': 'STRING', 'value': 'A'}
    assert candidate['certificate'] is False and candidate['final_authority'] == 'NONE'
    assert candidate['binding_status'] == candidate['applicability_status'] == 'UNRESOLVED'
    relation = result['queries'][0]['relation']
    assert relation['selected']['projection_pointer'] == '/1/handle'
    assert relation['selected']['criterion_pointer'] == '/1/criterion'
    assert not relation['closure_established'] and pk == before


def test_unrelated_objects_cannot_be_combined_into_a_tuple():
    result = relational.lookup(packet([dict(criterion='555-2002'), dict(handle='B')]), query())
    assert result['status'] == 'NOT_FOUND' and result['selected'] is None


def test_equal_projection_values_from_distinct_objects_remain_ambiguous():
    result = relational.lookup(packet([dict(criterion='555-2002', handle='B'), dict(criterion='666-2002', handle='B')]), query())
    assert result['status'] == 'AMBIGUOUS' and result['selected'] is None


@pytest.mark.parametrize('value', [2002, True, None, ['2002'], {'nested': '2002'}])
def test_string_criterion_does_not_alias_other_json_types(value):
    assert relational.lookup(packet([dict(criterion=value, handle='B')]), query())['selected'] is None


def test_exact_criterion_does_not_implicitly_apply_suffix_matching():
    q = query(); q['op'] = 'EQ'
    assert relational.lookup(packet(), q)['selected'] is None


def test_criterion_literal_must_be_in_exact_user_quote():
    q = query(); q['operand'] = '2001'
    assert relational.lookup(packet(), q)['status'] == 'UNSUPPORTED_USER_CRITERION'
    q = query(); q['quote'] = 'Use the record ending in 2001.'
    assert relational.lookup(packet(), q)['status'] == 'UNSUPPORTED_USER_CRITERION'


def test_assistant_proposal_cannot_be_used_as_original_user_criterion():
    pk = packet(); q = query(); q['r'] = next(s['source_id'] for s in pk['history'] if s['role'] == 'assistant')
    assert relational.lookup(pk, q)['status'] == 'UNSUPPORTED_USER_CRITERION'


def test_direct_field_names_support_escaped_json_pointer_keys():
    pk = packet([{'arbitrary/key': '555-2002', '~handle': 'B'}])
    q = query(); q.update(field='arbitrary/key', project='~handle')
    selected = relational.lookup(pk, q)['selected']
    assert selected['projection_pointer'] == '/0/~0handle' and selected['criterion_pointer'] == '/0/arbitrary~1key'


def test_arrays_cannot_project_arbitrary_first_identifier():
    pk = packet([dict(criterion='555-2002', handle=['B', 'C'])])
    assert relational.lookup(pk, query())['selected'] is None


def test_duplicate_assessments_do_not_make_a_decisive_candidate():
    result = relational.admit(dict(bindings=[query(), query()]), packet())
    assert not result['mismatch_candidates']
    assert all(r['admission'] == 'REJECTED_ARGUMENT_IDENTITY' for r in result['records'])


def test_ambiguous_old_and_new_records_are_not_silently_latest():
    pk = packet(); source = next(s for s in pk['history'] if s.get('kind') == 'result')
    second = copy.deepcopy(source); second['source_id'] = 'h999'; second['text'] = source['text'].replace('"B"', '"C"')
    pk['history'].append(second)
    assert relational.lookup(pk, query())['status'] == 'AMBIGUOUS'


def test_unparsed_native_result_is_visible_and_prevents_false_unique_scan():
    pk = packet(); source = next(s for s in pk['history'] if s.get('kind') == 'result')
    second = copy.deepcopy(source); second['source_id'] = 'h999'; second['text'] = '← TOOL_RESPONSE scan [ERROR]: broken'
    pk['history'].append(second)
    result = relational.lookup(pk, query())
    assert result['selected'] is None and result['source_gaps']


def test_literal_matching_does_not_certify_negation_or_semantic_role():
    pk = packet(); user = next(s for s in pk['history'] if s['source_id'] == 'h1')
    user['text'] = 'Do NOT use the record ending in 2002.'
    q = query(); q['quote'] = user['text']
    result = relational.lookup(pk, q)
    assert result['selected'] is not None
    assert result['binding_status'] == result['applicability_status'] == 'UNRESOLVED'
    # Query execution certifies only the selected literal relation. A model
    # interpreting this negated request as positive selection must be refuted.


def test_visibility_control_changes_only_current_values_in_fixed_source_view():
    pk = packet()
    blind = relational.construct_request(pk, 'model', 'blind')
    visible = relational.construct_request(pk, 'model', 'visible')
    b = json.loads(blind['messages'][1]['content']); v = json.loads(visible['messages'][1]['content'])
    assert blind['response_format'] == visible['response_format']
    assert blind['messages'][0] == visible['messages'][0]
    assert b['current_actions'] != v['current_actions']
    for k in b.keys() - {'current_actions', 'mode'}:
        assert b[k] == v[k]
