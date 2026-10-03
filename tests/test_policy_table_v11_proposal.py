"""Check the new proposal's useful components and counterexamples to unsafe inference."""
import pytest
from guardian_truth.policy_table_v11.citations import locate_citation
from guardian_truth.policy_table_v11.evidence_scope import validate_obligation_scope
from guardian_truth.policy_table.evaluate import same
from test_policy_table_v11 import comparison, store, target
from guardian_truth.policy_table_v11.witness import explicit_confirmation


@pytest.mark.parametrize('quote,source,conversion', [
    ('Only after approval.', 'Only after approval.', 'EXACT'),
    ('Only after\napproval.', '- Only after\r\n    approval.', 'WHITESPACE_ONLY'),
    (r'Only after\napproval.', '- Only after\r\n    approval.', 'ESCAPED_LINE_BREAKS_AND_WHITESPACE'),
    ('payement verified', 'Require payement verified.', 'EXACT'),
])
def test_citation_repairs_presentation_and_restores_source(quote, source, conversion):
    got = locate_citation(quote, source)
    assert got and source[got.start:got.end] == got.source_quote and got.conversion == conversion


@pytest.mark.parametrize('quote,source', [
    ('Only after approval', 'Only before approval'),
    ('payment verified', 'payement verified'),
    ('ID abc', 'ID ABC'),
    ('only if approved', 'only if approved; later only if approved'),
    ('"no approval"', 'no approval'),
    ('approval recorded', 'approval was recorded'),
    ('aaa','aaaa'),
])
def test_citation_does_not_repair_semantics_casing_or_ambiguity(quote, source):
    assert locate_citation(quote, source) is None


def test_dialogue_obligation_cannot_lower_to_argument_presence():
    expected = {'obligation_id': 'consent', 'required_scopes': ['DIALOGUE_STATE']}
    assert not validate_obligation_scope(expected, {'kind': 'COMPARE', 'lhs': 'args.record_id', 'op': 'exists'})['accepted']
    assert validate_obligation_scope(expected, {'kind': 'CONFIRMATION'})['accepted']
    assert not validate_obligation_scope(expected, {'kind': 'PRIOR_CALL', 'tool': 'inspect_b'})['accepted']
    proxy={'kind':'COMPARE','lhs':'args.amount','op':'exists'}
    assert not validate_obligation_scope(expected, {'kind':'ANY_OF','items':[{'kind':'CONFIRMATION'},proxy]})['accepted']
    assert validate_obligation_scope(expected, {'kind':'ALL_OF','items':[{'kind':'CONFIRMATION'},proxy]})['accepted']


@pytest.mark.parametrize('a,b', [('105', 105), ('ABC', 'abc'), (None, ''), ('true', True), (True, 1)])
def test_provenance_does_not_collapse_distinct_values(a,b):
    assert not same(a,b)
    assert same(42,42.0)  # Exact numeric equality already supported.


def test_all_arguments_known_and_schema_valid_do_not_imply_consent():
    # Both trajectories have the same argument values, same tools, valid types.
    prefix = '⟦USER⟧\nUse record X and amount 2.\n⟦ASSISTANT⟧\nConfirm apply_a: {"record_id":"X","amount":2}?\n'
    good = store(prefix+'⟦USER⟧\nYes\n')
    refused = store(prefix+'⟦USER⟧\nNo\n')
    assert explicit_confirmation(good,target(good)).value is True
    assert explicit_confirmation(refused,target(refused)).value is False
    # A value pool cannot distinguish these valid-schema calls.
    assert target(good)['arguments'] == target(refused)['arguments']


def test_missing_prior_provenance_is_not_necessarily_fabrication():
    s=store(response='→ TOOL_CALL apply_a: {"record_id":"NEW-X","amount":2}')
    # Without a declared closed-source contract there is no proof that NEW-X is forbidden.
    assert explicit_confirmation(s,target(s)).status == 'UNRESOLVED'
