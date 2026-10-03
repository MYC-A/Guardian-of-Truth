from guardian_truth.source_search.store import SourceStore
from guardian_truth.policy_table.schema import Rule
from guardian_truth.policy_table.compile import assemble
from guardian_truth.policy_table.evaluate import evaluate_table, evaluate_rule, resolve, Value
import json
import pytest


def source(value=True, *, extra='', entity='X', target='X'):
    return SourceStore({'prompt': '⟦SYSTEM⟧\nBefore tool_a, field_y must be true.\n[AVAILABLE TOOLS]\n- tool_a — apply\n    field_x: string!\n- tool_b — inspect\n    field_x: string!\n⟦USER⟧\nPlease act.\n⟦ASSISTANT⟧\n'
        '→ TOOL_CALL tool_b: {"field_x":"' + entity + '"}\n← TOOL_RESPONSE tool_b: {"field_x":"' + entity + '","field_y":' + ('true' if value else 'false') + '}\n' + extra,
        'response': '→ TOOL_CALL tool_a: {"field_x":"' + target + '"}'})


def rule(**changes):
    data = {'rule_id': 'r', 'clause_ids': ['clause_0'], 'trigger': {'kind': 'TOOL_CALL', 'tool': 'tool_a'},
        'modality': 'REQUIRES', 'conditions': [{'lhs': 'state.tool_b./field_y', 'op': '==', 'rhs': {'kind': 'LITERAL', 'value': True}}],
        'exceptions': [], 'prior_call': None, 'compile_status': 'COMPILED', 'not_compilable_reason': None}
    return Rule.model_validate({**data, **changes})


def test_three_values_error_only_and_target_binding():
    for value, expected in ((True, 0), (False, 1)):
        store = source(value)
        sample = {'rules': [rule().model_dump()], 'uncovered_clause_ids': []}
        table = assemble([store], [sample, sample, sample])
        result = evaluate_table(store, table)
        assert len(result['findings']) == expected
        assert result['emits_no_error'] is False
        if expected: assert result['findings'][0]['target_source_id'] == 't0'
    store = source(False, target='Y')
    assert resolve(store, 'state.tool_b./field_y', {'arguments': {'field_x': 'Y'}, 'source_id': 't0'}).status == 'UNRESOLVED'


def test_missing_latest_path_does_not_reuse_old_state():
    store = source(False, extra='→ TOOL_CALL tool_b: {"field_x":"X"}\n← TOOL_RESPONSE tool_b: {"field_x":"X"}\n')
    assert evaluate_rule(store, rule(), {'arguments': {'field_x': 'X'}, 'source_id': 't0'})['status'] == 'NO_FINDING'


def test_ambiguous_same_tool_pairing_is_unresolved():
    extra = '→ TOOL_CALL tool_b: {"field_x":"X"}\n→ TOOL_CALL tool_b: {"field_x":"X"}\n← TOOL_RESPONSE tool_b: {"field_x":"X","field_y":false}\n'
    store = source(True, extra=extra)
    assert resolve(store, 'state.tool_b./field_y', {'arguments': {'field_x': 'X'}, 'source_id': 't0'}).status == 'UNRESOLVED'


def test_unknown_exception_suppresses_even_explicit_violation():
    store = source(False)
    r = rule(exceptions=[[{'lhs': 'state.tool_b./absent', 'op': '==', 'rhs': {'kind': 'LITERAL', 'value': True}}]])
    assert evaluate_rule(store, r, {'arguments': {'field_x': 'X'}, 'source_id': 't0'})['reason'] == 'exception_true_or_unresolved'


def test_missing_path_is_not_false_even_for_not_exists():
    store = source(False)
    r = rule(conditions=[{'lhs': 'state.tool_b./absent', 'op': 'not_exists'}])
    assert evaluate_rule(store, r, {'arguments': {'field_x': 'X'}, 'source_id': 't0'})['reason'] == 'unresolved_condition'


def test_ambiguous_confirmation_is_not_proof_of_violation():
    store = source(False)
    r = rule(modality='REQUIRES_USER_CONFIRMATION', conditions=[])
    target = {'arguments': {'field_x': 'X'}, 'source_id': 't0'}
    assert evaluate_rule(store, r, target, {'user.confirmation_of_trigger': Value('UNRESOLVED')})['status'] == 'NO_FINDING'
    assert evaluate_rule(store, r, target, {'user.confirmation_of_trigger': Value('RESOLVED', False, ('h1',))})['status'] == 'ERROR'


def test_prior_call_same_entity_and_strict_order():
    store = source(True)
    r = rule(modality='REQUIRES_PRIOR_CALL', prior_call='tool_b', conditions=[])
    assert evaluate_rule(store, r, {'arguments': {'field_x': 'X'}, 'source_id': 't0'})['status'] == 'NO_FINDING'
    assert evaluate_rule(store, r, {'arguments': {'field_x': 'Y'}, 'source_id': 't0'})['status'] == 'NO_FINDING'
    r = rule(modality='REQUIRES_PRIOR_CALL', prior_call='tool_c', conditions=[])
    assert evaluate_rule(store, r, {'arguments': {'field_x': 'X'}, 'source_id': 't0'})['status'] == 'ERROR'


def test_requires_and_forbids_have_distinct_direction():
    store = source(False); target = {'arguments': {'field_x': 'X'}, 'source_id': 't0'}
    assert evaluate_rule(store, rule(), target)['status'] == 'ERROR'
    assert evaluate_rule(store, rule(modality='FORBIDS'), target)['status'] == 'NO_FINDING'


def records_store(records, target_args=None):
    original = source(True)
    prefix = original.raw['prompt'].split('→ TOOL_CALL')[0]
    return SourceStore({'prompt': prefix + '← TOOL_RESPONSE tool_b: ' + json.dumps(records) + '\n',
        'response': '→ TOOL_CALL tool_a: ' + json.dumps(target_args or {'field_x': 'X'})})


def test_array_selection_binds_the_matching_record_not_the_first():
    store = records_store({'items': [{'field_x': 'Y', 'field_y': False}, {'field_x': 'X', 'field_y': True}]})
    target = {'arguments': {'field_x': 'X'}, 'source_id': 't0'}
    assert resolve(store, 'state.tool_b./items/*/field_y', target).value is True
    ambiguous = records_store({'items': [{'field_x': 'X', 'field_y': False}, {'field_x': 'X', 'field_y': False}]})
    assert resolve(ambiguous, 'state.tool_b./items/*/field_y', target).status == 'UNRESOLVED'


def test_nested_entity_and_two_string_arguments_need_complete_binding():
    store = records_store({'field_y': False}, {'subject': {'field_x': 'X'}})
    assert resolve(store, 'state.tool_b./field_y', {'arguments': {'subject': {'field_x': 'X'}}, 'source_id': 't0'}).status == 'UNRESOLVED'
    store = records_store({'subject': {'field_x': 'Y'}, 'field_y': False}, {'subject': {'field_x': 'X'}})
    assert resolve(store, 'state.tool_b./field_y', {'arguments': {'subject': {'field_x': 'X'}}, 'source_id': 't0'}).status == 'UNRESOLVED'
    store = records_store({'subject': {'field_x': 'X'}, 'field_y': False}, {'subject': {'field_x': 'X'}})
    assert resolve(store, 'state.tool_b./field_y', {'arguments': {'subject': {'field_x': 'X'}}, 'source_id': 't0'}).value is False
    store = records_store({'field_x': 'X', 'field_y': False})
    assert resolve(store, 'state.tool_b./field_y', {'arguments': {'field_x': 'X', 'field_z': 'Y'}, 'source_id': 't0'}).status == 'UNRESOLVED'


def test_exception_cannot_use_another_entitys_approval():
    store = records_store({'items': [{'field_x': 'X', 'field_y': False, 'field_z': False},
        {'field_x': 'Y', 'field_y': False, 'field_z': True}]})
    r = rule(conditions=[{'lhs': 'state.tool_b./items/*/field_y', 'op': '==', 'rhs': {'kind': 'LITERAL', 'value': True}}],
        exceptions=[[{'lhs': 'state.tool_b./items/*/field_z', 'op': '==', 'rhs': {'kind': 'LITERAL', 'value': True}}]])
    assert evaluate_rule(store, r, {'arguments': {'field_x': 'X'}, 'source_id': 't0'})['status'] == 'ERROR'
    # Same entity, explicit exception: the violation must be suppressed.
    store = records_store({'items': [{'field_x': 'X', 'field_y': False, 'field_z': True}]})
    assert evaluate_rule(store, r, {'arguments': {'field_x': 'X'}, 'source_id': 't0'})['status'] == 'NO_FINDING'


def test_exception_or_groups_and_false_plus_unknown_conjunction():
    store = source(False)
    false = {'lhs': 'state.tool_b./field_y', 'op': '==', 'rhs': {'kind': 'LITERAL', 'value': True}}
    unknown = {'lhs': 'state.tool_b./absent', 'op': '==', 'rhs': {'kind': 'LITERAL', 'value': True}}
    target = {'arguments': {'field_x': 'X'}, 'source_id': 't0'}
    assert evaluate_rule(store, rule(exceptions=[[false, unknown]]), target)['status'] == 'ERROR'
    assert evaluate_rule(store, rule(exceptions=[[false], [unknown]]), target)['status'] == 'NO_FINDING'


@pytest.mark.parametrize('date,expected', [('2030-01-01T00:00:00Z', 'ERROR'),
    ('2030-01-01T00:00:00', 'NO_FINDING'), ('not-a-date', 'NO_FINDING')])
def test_time_comparison_requires_an_unambiguous_timezone(date, expected):
    store = records_store({'field_x': 'X', 'field_y': date})
    r = rule(conditions=[{'lhs': 'state.tool_b./field_y', 'op': 'after',
        'rhs': {'kind': 'LITERAL', 'value': '2031-01-01T00:00:00Z'}}])
    assert evaluate_rule(store, r, {'arguments': {'field_x': 'X'}, 'source_id': 't0'})['status'] == expected


def test_latest_unparseable_result_is_not_replaced_by_older_value():
    store = source(False, extra='→ TOOL_CALL tool_b: {"field_x":"X"}\n← TOOL_RESPONSE tool_b: result unavailable\n')
    assert resolve(store, 'state.tool_b./field_y', {'arguments': {'field_x': 'X'}, 'source_id': 't0'}).status == 'UNRESOLVED'


def test_identity_binding_is_typed_even_in_nested_containers():
    store = records_store({'subject': {'field_x': True}, 'field_y': False}, {'subject': {'field_x': 1}})
    assert resolve(store, 'state.tool_b./field_y', {'arguments': {'subject': {'field_x': 1}}, 'source_id': 't0'}).status == 'UNRESOLVED'


def test_latest_other_entity_does_not_hide_previous_matching_result():
    store = source(False, extra='← TOOL_RESPONSE tool_b: {"field_x":"Y"}\n')
    value = resolve(store, 'state.tool_b./field_y', {'arguments': {'field_x': 'X'}, 'source_id': 't0'})
    assert value.status == 'RESOLVED' and value.value is False


def test_matching_array_record_with_missing_field_blocks_stale_reuse():
    store = records_store({'items': [{'field_x': 'X', 'field_y': False}]})
    updated = SourceStore({**store.raw, 'prompt': store.raw['prompt'] +
        '← TOOL_RESPONSE tool_b: {"items":[{"field_x":"X"},{"field_x":"Y","field_y":false}]}\n'})
    value = resolve(updated, 'state.tool_b./items/*/field_y', {'arguments': {'field_x': 'X'}, 'source_id': 't0'})
    assert value.status == 'UNRESOLVED'


def test_user_tool_attempt_does_not_satisfy_required_assistant_call():
    store = source(True)
    user_history = store.raw['prompt'].replace('⟦ASSISTANT⟧', '⟦USER⟧')
    store = SourceStore({**store.raw, 'prompt': user_history})
    r = rule(modality='REQUIRES_PRIOR_CALL', prior_call='tool_b', conditions=[])
    assert evaluate_rule(store, r, {'arguments': {'field_x': 'X'}, 'source_id': 't0'})['status'] == 'ERROR'


def test_json_pointer_root_empty_key_and_escaped_key_are_distinct():
    store = records_store({'field_x': 'X', '': False, 'a/b~c': True})
    target = {'arguments': {'field_x': 'X'}, 'source_id': 't0'}
    assert resolve(store, 'state.tool_b./', target).value is False
    assert resolve(store, 'state.tool_b./a~1b~0c', target).value is True
    assert isinstance(resolve(store, 'state.tool_b.', target).value, dict)


def test_new_value_comparison_is_not_mistaken_for_entity_binding():
    store = records_store({'field_x': 'X', 'field_y': 3})
    r = rule(modality='FORBIDS', conditions=[{'lhs': 'args.field_y', 'op': '!=',
        'rhs': {'kind': 'PATH', 'path': 'state.tool_b./field_y'}}])
    assert evaluate_rule(store, r, {'arguments': {'field_x': 'X', 'field_y': 4}, 'source_id': 't0'})['status'] == 'ERROR'
    assert evaluate_rule(store, r, {'arguments': {'field_x': 'X', 'field_y': 3}, 'source_id': 't0'})['status'] == 'NO_FINDING'
    assert evaluate_rule(store, r, {'arguments': {'field_x': 'Y', 'field_y': 4}, 'source_id': 't0'})['status'] == 'NO_FINDING'
    # Without a remaining join key a comparison cannot borrow another entity.
    assert evaluate_rule(store, r, {'arguments': {'field_y': 4}, 'source_id': 't0'})['status'] == 'NO_FINDING'


def test_numeric_entity_without_any_binding_is_not_a_matching_result():
    store = records_store({'field_z': 999, 'field_y': False})
    assert resolve(store, 'state.tool_b./field_y', {'arguments': {'field_x': 1}, 'source_id': 't0'}).status == 'UNRESOLVED'


def test_full_array_condition_keeps_entity_binding_and_typed_elements():
    store = records_store({'field_x': 'X', 'field_y': ['A', 'B']})
    r = rule(modality='FORBIDS', conditions=[{'lhs': 'args.field_y', 'op': '!=',
        'rhs': {'kind': 'PATH', 'path': 'state.tool_b./field_y'}}])
    assert evaluate_rule(store, r, {'arguments': {'field_x': 'X', 'field_y': ['A']}, 'source_id': 't0'})['status'] == 'ERROR'
    assert evaluate_rule(store, r, {'arguments': {'field_x': 'Y', 'field_y': ['A']}, 'source_id': 't0'})['status'] == 'NO_FINDING'
