import json
from benchmarks.mutations_v10.generate import generate, rule_pairs, rendering_controls, identifier_mutations
from guardian_truth.policy_table.compile import assemble
from guardian_truth.policy_table.evaluate import evaluate_rule
from guardian_truth.source_search.store import SourceStore
from test_policy_table_eval import source, rule, records_store


def table_for(store, r):
    sample = {'rules': [r.model_dump()], 'uncovered_clause_ids': []}
    return assemble([store], [sample, sample, sample])


def test_state_pairs_have_only_rule_local_negative_labels_and_preserve_original():
    store = source(False); original = dict(store.raw)
    table = table_for(store, rule())
    inputs, expected, summary = generate([{'id': 'synthetic', **store.raw}], {table.policy_sha256: table})
    states = [e for e in expected if e['kind'] == 'STATE_CONDITION']
    assert {e['expected_rule_status'] for e in states} == {'ERROR', 'NO_FINDING'}
    assert all(e['whole_case_label'] is None for e in states if e['expected_rule_status'] == 'NO_FINDING')
    assert all(e['whole_case_label_basis'].startswith('CONDITIONAL') for e in states if e['expected_rule_status'] == 'ERROR')
    assert store.raw == original
    assert summary['status'] == 'PREPARED_INCOMPLETE_NOT_FULL_BENCHMARK'
    assert summary['eligibility_gaps']
    assert {i['id'] for i in inputs} == {e['id'] for e in expected}


def test_unknown_or_other_entity_cannot_acquire_a_constructed_rule_label():
    good = source(False); table = table_for(good, rule())
    assert not list(rule_pairs(source(False, target='Y'), table))
    ambiguous = records_store({'items': [{'field_x': 'X', 'field_y': False}, {'field_x': 'X', 'field_y': True}]})
    r = rule(conditions=[{'lhs': 'state.tool_b./items/*/field_y', 'op': '==', 'rhs': {'kind': 'LITERAL', 'value': True}}])
    assert not list(rule_pairs(ambiguous, table_for(ambiguous, r)))


def test_exception_pairs_require_a_proved_violating_branch():
    store = records_store({'field_x': 'X', 'field_y': False, 'field_z': False})
    r = rule(exceptions=[[{'lhs': 'state.tool_b./field_z', 'op': '==', 'rhs': {'kind': 'LITERAL', 'value': True}}]])
    pairs = list(rule_pairs(store, table_for(store, r)))
    exceptions = [pair for pair in pairs if pair[0].get('subkind') == 'STATE_EXCEPTION']
    assert exceptions and {v['expected_rule_status'] for v in exceptions[0]} == {'ERROR', 'NO_FINDING'}
    unknown = source(False)
    # This table's exception has no resolvable observation in the new input.
    assert not list(rule_pairs(unknown, table_for(store, r)))


def test_rendering_control_preserves_all_native_values_and_text_order():
    store = source(False)
    controls = list(rendering_controls(store))
    assert controls
    for control in controls:
        changed = SourceStore(control['row'])
        assert [e.value for e in changed.history_events] == [e.value for e in store.history_events]
        assert [e.value for e in changed.target_events] == [e.value for e in store.target_events]
        assert control['expected_relation'] == 'SAME_BASE_DECISION'


def test_identifier_mutation_requires_input_format_never_a_name_heuristic():
    assert not list(identifier_mutations(source()))
    old = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
    store = source(entity=old, target=old)
    store = SourceStore({**store.raw, 'prompt': store.raw['prompt'].replace('field_x: string!', 'field_x: string! [format: uuid]')})
    variants = list(identifier_mutations(store))
    assert variants and variants[0]['whole_case_label'] == 1
    assert variants[0]['change']['new_value'] not in store.raw['prompt']


def test_uncompiled_policies_never_report_a_complete_required_benchmark():
    inputs, expected, summary = generate([{'id': 'synthetic', **source().raw}], {})
    assert summary['unavailable'][0]['reason'] == 'policy_not_compiled'
    assert summary['mutants'] < 120 and summary['status'].startswith('PREPARED_INCOMPLETE')
    assert all(e['kind'] == 'NEGATIVE_CONTROL' for e in expected)


def test_mutation_can_change_prior_state_on_rhs_without_changing_entity_or_target_value():
    old = records_store({'field_x': 'X', 'field_y': 3})
    store = SourceStore({'prompt': old.raw['prompt'].replace('field_x: string!', 'field_x: string!\n    field_y: integer'),
        'response': '→ TOOL_CALL tool_a: {"field_x":"X","field_y":4}'})
    r = rule(modality='FORBIDS', conditions=[{'lhs': 'args.field_y', 'op': '!=',
        'rhs': {'kind': 'PATH', 'path': 'state.tool_b./field_y'}}])
    pairs = list(rule_pairs(store, table_for(store, r)))
    assert pairs and {v['expected_rule_status'] for v in pairs[0]} == {'ERROR', 'NO_FINDING'}
    assert all(v['row']['response'] == store.raw['response'] for v in pairs[0])
    assert all(v['change']['path'] == 'state.tool_b./field_y' for v in pairs[0])
