from dataclasses import replace
import json

import pytest

from guardian_truth.vnext.identity_aliases_v2 import IdentityAliasIndex, IdentityDeclaration
from guardian_truth.vnext.ledger import EvidenceLedger
from guardian_truth.vnext.normalize import normalize
from guardian_truth.vnext.types import ToolIdentity


TOOL = ToolIdentity('read_records', 'fixture', 'v1', 'source-schema-v1')
DECLARATION = IdentityDeclaration(TOOL, 'records', ('items', '*'), 'id', ('name',),
    'explicit controlled source: items are records; id is stable string identity; name is display alias', True)


def ledger(*results, complete=True, tool=TOOL):
    text = ''
    for index, result in enumerate(results):
        text += f'⟦ASSISTANT_TOOL_CALL name="read_records" call_id="c{index}"⟧\n{{}}\n'
        text += f'⟦TOOL_RESULT name="read_records" call_id="c{index}" requestor="assistant"⟧\n' + json.dumps(result) + '\n'
    return EvidenceLedger.from_events(normalize(text, '', tool_identities=(tool,)),
        history_complete=complete, completeness_basis='complete controlled source prefix' if complete else None)


def test_duplicate_display_names_remain_two_stable_id_candidates():
    source = ledger({'items': [{'id': 'id-1', 'name': 'Alex'}, {'id': 'id-2', 'name': 'Alex'}]})
    result = IdentityAliasIndex(source, (DECLARATION,)).resolve('Alex')
    assert {entity.value for entity in result.entities} == {'id-1', 'id-2'}
    assert result.searched_source_complete
    assert 'name_identity_ambiguous' in result.unresolved_terms
    assert {observation.record_path for observation in result.observations} == {('items', '0'), ('items', '1')}


def test_record_groups_prevent_cross_product_of_names_and_ids():
    source = ledger({'items': [{'id': 'id-1', 'name': 'Alex'}, {'id': 'id-2', 'name': 'Bob'}]})
    index = IdentityAliasIndex(source, (DECLARATION,))
    assert [entity.value for entity in index.resolve('Alex').entities] == ['id-1']
    assert [entity.value for entity in index.resolve('Bob').entities] == ['id-2']


def test_authoritative_rename_snapshot_preserves_historical_binding():
    source = ledger({'items': [{'id': 'id-1', 'name': 'Alex'}]}, {'items': [{'id': 'id-1', 'name': 'Bob'}]})
    index = IdentityAliasIndex(source, (DECLARATION,))
    assert [entity.value for entity in index.resolve('Alex', before_index=1).entities] == ['id-1']
    assert not index.resolve('Alex').entities
    assert [entity.value for entity in index.resolve('Bob').entities] == ['id-1']
    assert index.resolve('Alex').unresolved_terms == ('name_not_observed_not_absent',)


def test_partial_alias_record_cannot_remove_previous_observation():
    source = ledger({'items': [{'id': 'id-1', 'name': 'Alex'}]}, {'items': [{'id': 'id-1'}]})
    result = IdentityAliasIndex(source, (DECLARATION,)).resolve('Alex')
    assert [entity.value for entity in result.entities] == ['id-1']
    assert not result.searched_source_complete
    assert 'declared_alias_field_missing' in result.unresolved_terms


def test_future_incomplete_source_does_not_rewrite_prior_query_completeness():
    source = ledger({'items': [{'id': 'id-1', 'name': 'Alex'}]}, {'wrong': []})
    index = IdentityAliasIndex(source, (DECLARATION,))
    assert index.resolve('Alex', before_index=1).searched_source_complete
    assert not index.resolve('Alex').searched_source_complete


def test_unversioned_or_incompatible_result_cannot_borrow_identity_declaration():
    source = ledger({'items': [{'id': 'id-1', 'name': 'Alex'}]}, tool=replace(TOOL, version='v2'))
    result = IdentityAliasIndex(source, (DECLARATION,)).resolve('Alex')
    assert not result.entities and not result.searched_source_complete
    assert 'result_identity_semantics_undeclared' in result.unresolved_terms


def test_user_assertions_and_tool_arguments_do_not_establish_aliases():
    text = '⟦USER⟧\n{"id":"id-1","name":"Alex"}\n'
    text += '⟦ASSISTANT_TOOL_CALL name="read_records" call_id="c0"⟧\n{"items":[{"id":"id-1","name":"Alex"}]}'
    source = EvidenceLedger.from_events(normalize(text, '', tool_identities=(TOOL,)))
    result = IdentityAliasIndex(source, (DECLARATION,)).resolve('Alex')
    assert not result.entities and not result.searched_source_complete


def test_distinct_namespaces_do_not_collapse_identical_local_ids():
    source = ledger({'items': [{'id': 'id-1', 'name': 'Alex'}]}, {'items': [{'id': 'id-1', 'name': 'Alex'}]})
    other = replace(TOOL, name='other_records')
    events = tuple(replace(event, tool=other) if event.index >= 2 else event for event in source.events)
    source = replace(source, events=events)
    declarations = (DECLARATION, replace(DECLARATION, tool=other, namespace='other-system'))
    result = IdentityAliasIndex(source, declarations).resolve('Alex')
    assert len(result.entities) == 2
    assert {entity.namespace for entity in result.entities} == {'records', 'other-system'}


def test_same_result_conflicting_snapshots_are_not_last_wins():
    source = ledger({'items': [{'id': 'id-1', 'name': 'Alex'}, {'id': 'id-1', 'name': 'Bob'}]})
    index = IdentityAliasIndex(source, (DECLARATION,))
    assert index.resolve('Alex').entities == index.resolve('Bob').entities
    assert len(index.observations) == 2


@pytest.mark.parametrize('record', [{'name': 'Alex'}, {'id': True, 'name': 'Alex'}, {'id': 1, 'name': 'Alex'}])
def test_missing_or_wrongly_typed_identity_is_unknown_not_a_forced_binding(record):
    result = IdentityAliasIndex(ledger({'items': [record]}), (DECLARATION,)).resolve('Alex')
    assert not result.entities and not result.searched_source_complete


def test_non_snapshot_declaration_keeps_both_historical_aliases():
    source = ledger({'items': [{'id': 'id-1', 'name': 'Alex'}]}, {'items': [{'id': 'id-1', 'name': 'Bob'}]})
    index = IdentityAliasIndex(source, (replace(DECLARATION, full_alias_snapshot=False),))
    assert index.resolve('Alex').entities == index.resolve('Bob').entities


def test_candidate_space_is_not_top_k_on_long_result():
    source = ledger({'items': [{'id': 'id-' + str(index), 'name': 'Alex'} for index in range(2000)]})
    result = IdentityAliasIndex(source, (DECLARATION,)).resolve('Alex')
    assert len(result.entities) == len(result.observations) == 2000
    assert result.searched_source_complete


def test_alias_query_uses_name_index_not_every_record_in_the_trace():
    source = ledger({'items': [{'id': 'id-' + str(index), 'name': 'Alex' if index == 19 else 'Bob'} for index in range(2000)]})
    result = IdentityAliasIndex(source, (DECLARATION,)).resolve('Alex')
    assert len(result.entities) == result.searched_observation_count == 1
    assert result.entities[0].value == 'id-19'


def test_explicit_empty_full_snapshot_removes_prior_alias_without_proving_absence():
    source = ledger({'items': [{'id': 'id-1', 'name': 'Alex'}]}, {'items': [{'id': 'id-1', 'name': []}]})
    result = IdentityAliasIndex(source, (DECLARATION,)).resolve('Alex')
    assert not result.entities
    assert 'name_not_observed_not_absent' in result.unresolved_terms
    assert 'not current-state or absence proof' in result.semantics


def test_incomplete_trace_preserves_positive_candidates_without_claiming_complete_search():
    source = ledger({'items': [{'id': 'id-1', 'name': 'Alex'}]}, complete=False)
    result = IdentityAliasIndex(source, (DECLARATION,)).resolve('Alex')
    assert result.entities and not result.searched_source_complete


def test_unbound_time_and_duplicate_contracts_fail_explicitly():
    source = ledger({'items': [{'id': 'id-1', 'name': 'Alex'}]})
    assert IdentityAliasIndex(source, (DECLARATION,)).resolve('Alex', before_index=10).unresolved_terms == ('identity_time_unbound',)
    with pytest.raises(ValueError):
        IdentityAliasIndex(source, (DECLARATION, DECLARATION))


def test_result_shaped_user_event_does_not_establish_a_tool_identity_observation():
    source = ledger({'items': [{'id': 'id-1', 'name': 'Alex'}]})
    source = EvidenceLedger.from_events((source.events[0], replace(source.events[1], actor='user')),
        history_complete=source.history_complete, completeness_basis=source.completeness_basis)
    result = IdentityAliasIndex(source, (DECLARATION,)).resolve('Alex')
    assert not result.entities and not result.searched_source_complete
    assert 'result_identity_role_untrusted' in result.unresolved_terms
