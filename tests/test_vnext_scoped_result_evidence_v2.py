from dataclasses import replace
import json

import pytest

from guardian_truth.vnext.identity_aliases_v2 import IdentityAliasIndex, IdentityDeclaration
from guardian_truth.vnext.ledger import EvidenceLedger
from guardian_truth.vnext.normalize import normalize
from guardian_truth.vnext.scoped_result_evidence_v2 import ScopedFieldQuery, prove_scoped_field, query_alias_field
from guardian_truth.vnext.types import EntityRef, ToolIdentity, Truth


TOOL = ToolIdentity('read_records', 'fixture', 'v1', 'declared-schema')
DECLARATION = IdentityDeclaration(TOOL, 'records', ('items', '*'), 'id', ('name',), 'explicit controlled record identity definition', True)


def index(items, *, complete=True, declaration=DECLARATION):
    prompt = '⟦ASSISTANT_TOOL_CALL name="read_records" call_id="c"⟧\n{}\n'
    prompt += '⟦TOOL_RESULT name="read_records" call_id="c" requestor="assistant"⟧\n' + json.dumps({'items': items})
    ledger = EvidenceLedger.from_events(normalize(prompt, '', tool_identities=(TOOL,)),
        history_complete=complete, completeness_basis='controlled complete prefix' if complete else None)
    return IdentityAliasIndex(ledger, (declaration,))


def test_name_ambiguity_preserves_scalar_true_false_worlds_without_forcing_binding():
    source = index([{'id': 'a', 'name': 'Alex', 'price': 42}, {'id': 'b', 'name': 'Alex', 'price': 99}])
    result = query_alias_field(source, 'Alex', 1, ('price',), '42')
    assert result['value'] is Truth.UNKNOWN
    assert {proof.value for proof in result['proofs']} == {Truth.TRUE, Truth.FALSE}
    assert len(result['candidates'].entities) == 2


def test_record_grouping_does_not_attribute_other_record_price_to_selected_identity():
    source = index([{'id': 'a', 'name': 'Alex', 'price': 42}, {'id': 'b', 'name': 'Bob', 'price': 99}])
    proof = prove_scoped_field(ScopedFieldQuery(EntityRef('id', 'a', 'records'), 1, ('price',), '99'), source)
    assert proof.value is Truth.FALSE
    assert proof.refuting_paths == (('items', '0', 'price'),)
    assert 'NOT_CURRENT_STATE_COMPLETION_OR_CAUSALITY' in proof.scope


@pytest.mark.parametrize('actual,expected,truth', [(1.0, '1', Truth.TRUE), (True, '1', Truth.FALSE),
    ('ready', '"ready"', Truth.TRUE), (None, 'null', Truth.TRUE), ([1, 2], '[1,2]', Truth.TRUE)])
def test_scalar_and_structural_json_values_have_typed_equality_not_boolean_coercion(actual, expected, truth):
    source = index([{'id': 'a', 'name': 'Alex', 'value': actual}])
    result = query_alias_field(source, 'Alex', 1, ('value',), expected)
    assert result['value'] is truth


def test_same_stable_identity_conflicting_result_values_produce_both_not_last_wins():
    source = index([{'id': 'a', 'name': 'Alex', 'price': 42}, {'id': 'a', 'name': 'Alex', 'price': 99}])
    result = query_alias_field(source, 'Alex', 1, ('price',), '42')
    assert result['value'] is Truth.BOTH
    assert len(result['proofs']) == 1


def test_missing_record_field_or_missing_identity_is_unknown_not_false():
    source = index([{'id': 'a', 'name': 'Alex'}])
    assert query_alias_field(source, 'Alex', 1, ('price',), '42')['value'] is Truth.UNKNOWN
    assert query_alias_field(source, 'missing', 1, ('price',), '42')['value'] is Truth.UNKNOWN


def test_wrong_namespace_or_version_cannot_borrow_record_field_evidence():
    source = index([{'id': 'a', 'name': 'Alex', 'price': 42}])
    query = ScopedFieldQuery(EntityRef('id', 'a', 'wrong-system'), 1, ('price',), '42')
    assert prove_scoped_field(query, source).value is Truth.UNKNOWN
    incompatible = index([{'id': 'a', 'name': 'Alex', 'price': 42}], declaration=replace(DECLARATION, tool=replace(TOOL, version='v2')))
    assert query_alias_field(incompatible, 'Alex', 1, ('price',), '42')['value'] is Truth.UNKNOWN


def test_call_arguments_or_unbound_time_cannot_prove_result_field():
    source = index([{'id': 'a', 'name': 'Alex', 'price': 42}])
    query = ScopedFieldQuery(EntityRef('id', 'a', 'records'), 0, ('price',), '42')
    assert prove_scoped_field(query, source).value is Truth.UNKNOWN
    assert prove_scoped_field(replace(query, event_index=20), source).value is Truth.UNKNOWN


def test_incomplete_alias_candidate_search_cannot_be_used_for_definite_binding_verdict():
    source = index([{'id': 'a', 'name': 'Alex', 'price': 42}], complete=False)
    result = query_alias_field(source, 'Alex', 1, ('price',), '42')
    assert result['proofs'][0].value is Truth.TRUE
    assert result['value'] is Truth.UNKNOWN


def test_malformed_other_record_blocks_conclusive_negative():
    source = index([{'id': 'a', 'name': 'Alex', 'price': 99}, {'name': 'Alex', 'price': 42}])
    query = ScopedFieldQuery(EntityRef('id', 'a', 'records'), 1, ('price',), '42')
    assert prove_scoped_field(query, source).value is Truth.UNKNOWN


def test_noncanonical_or_nonfinite_expected_values_are_rejected():
    with pytest.raises(ValueError):
        ScopedFieldQuery(EntityRef('id', 'a', 'records'), 1, ('price',), 'NaN')
    with pytest.raises(ValueError):
        ScopedFieldQuery(EntityRef('id', 'a', 'records'), 1, ('price',), ' 42 ')


def test_scoped_field_proof_uses_identity_event_index_not_every_other_record():
    source = index([{'id': str(number), 'name': 'Alex', 'price': number} for number in range(2000)])
    query = ScopedFieldQuery(EntityRef('id', '119', 'records'), 1, ('price',), '119')
    proof = prove_scoped_field(query, source)
    assert proof.value is Truth.TRUE
    assert proof.searched_record_count == 1
    with pytest.raises(TypeError):
        source.records_by_entity_event[(query.entity, 'fake')] = ()
