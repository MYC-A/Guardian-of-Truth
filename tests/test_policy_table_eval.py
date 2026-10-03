from guardian_truth.source_search.store import SourceStore
from guardian_truth.policy_table.schema import Rule
from guardian_truth.policy_table.compile import assemble
from guardian_truth.policy_table.evaluate import evaluate_table, evaluate_rule, resolve, Value


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
