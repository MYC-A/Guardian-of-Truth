"""General counterexamples for proof provenance, consent and exact agreement (no gold/API)."""
from decimal import localcontext
import json
import pytest
from test_policy_table_v11 import store, policy, target, atomic, comparison
from guardian_truth.source_search.store import SourceStore
from guardian_truth.policy_table_v11.compile import admit, assemble, canonical
from guardian_truth.policy_table_v11.evaluate import evaluate_atom, evaluate_table
from guardian_truth.policy_table_v11.witness import explicit_confirmation, current_datetime, contains_value


@pytest.mark.parametrize('prefix', ['', 'P.', 'group/', 'prefix-'])
def test_symmetric_identifier_boundaries(prefix):
    assert contains_value(prefix + 'X', 'X') is (prefix == '')
    assert contains_value('record X.', 'X')


@pytest.mark.parametrize('text,reply', [
    ('Is record X already closed?', 'No'), ('Is record X already closed?', None),
    ('Is X the record to inspect?', 'Yes'), ('Confirm action on X?', 'Yes'),
])
def test_facts_and_incomplete_action_are_not_consent(text, reply):
    extra = '⟦ASSISTANT⟧\n' + text + ('\n⟦USER⟧\n' + reply if reply else '') + '\n'
    result = explicit_confirmation(store(extra), target(store(extra)))
    assert result.status == 'UNRESOLVED' and result.value is None


@pytest.mark.parametrize('tool,amount,reply,want', [
    ('apply_a', 2, 'Yes', True), ('apply_a', 2, 'No', False),
    ('apply_a', 999, 'Yes', None), ('inspect_b', 2, 'Yes', None),
    ('apply_a', True, 'Yes', None), ('apply_a', 2, 'Yes, I refuse to approve', None),
    ('apply_a', 2, 'Yes, unless the record is active', None),
    ('apply_a', 2, 'No objections: "No"', None),
    ('apply_a', 2, 'Да', True), ('apply_a', 2, 'Нет', False),
])
def test_complete_action_and_entire_reply(tool, amount, reply, want):
    frame = tool + ': ' + json.dumps({'record_id': 'X', 'amount': amount})
    s = store('⟦ASSISTANT⟧\nConfirm ' + frame + '?\n⟦USER⟧\n' + reply + '\n')
    got = explicit_confirmation(s, target(s))
    assert got.value is want
    assert got.status == ('UNRESOLVED' if want is None else 'RESOLVED')


@pytest.mark.parametrize('actor', ['USER', 'SYSTEM'])
@pytest.mark.parametrize('collection', [False, True])
def test_observation_requires_assistant_call(actor, collection):
    payload = {'record_id': 'X', 'enabled': False, 'values': [False]}
    s = store('⟦' + actor + '⟧\n→ TOOL_CALL inspect_b: {"record_id":"X"}\n'
              '← TOOL_RESPONSE inspect_b: ' + json.dumps(payload) + '\n')
    expr = comparison('state.inspect_b./values/*' if collection else 'state.inspect_b./enabled', value=True,
                      **({'quantifier': 'ALL'} if collection else {}))
    got = evaluate_atom(s, atomic(modality='REQUIRES', confirmation=None, condition=expr), target(s))
    assert got['value'] == 'UNRESOLVED' and not got['finding']


@pytest.mark.parametrize('collection', [False, True])
def test_orphan_latest_result_does_not_reuse_earlier_valid_value(collection):
    s = store('⟦ASSISTANT⟧\n→ TOOL_CALL inspect_b: {"record_id":"X"}\n'
              '← TOOL_RESPONSE inspect_b: {"record_id":"X","enabled":false,"values":[false]}\n'
              '← TOOL_RESPONSE inspect_b: {"record_id":"X","enabled":false,"values":[false]}\n')
    expr = comparison('state.inspect_b./values/*' if collection else 'state.inspect_b./enabled', value=True,
                      **({'quantifier': 'ALL'} if collection else {}))
    assert evaluate_atom(s, atomic(modality='REQUIRES', confirmation=None, condition=expr), target(s))['value'] == 'UNRESOLVED'


@pytest.mark.parametrize('parent', [None, 'Y', 'X'])
def test_TARGET_preserves_parent_and_child_identity(parent):
    result = {'items': {'I': {'item_id': 'I', 'enabled': False}}}
    if parent: result['record_id'] = parent
    s = store('⟦ASSISTANT⟧\n→ TOOL_CALL inspect_b: {}\n← TOOL_RESPONSE inspect_b: ' + json.dumps(result) + '\n',
              response='→ TOOL_CALL apply_a: {"record_id":"X","item_id":"I","amount":2}')
    # Reader intentionally has no identity arguments; parent must come from result lineage.
    s = SourceStore({**s.raw, 'prompt': s.raw['prompt'].replace('- inspect_b — inspect a record\n    record_id: string!', '- inspect_b — inspect records')
                    .replace('    amount: number!', '    amount: number!\n    item_id: string!')})
    atom = atomic(modality='REQUIRES', confirmation=None, condition=comparison('state.inspect_b./items/{key}/enabled',
        value=True, quantifier='TARGET', binding={'argument': 'item_id', 'record_field': '$key'}))
    assert admit({'atoms': [atom.model_dump()]}, policy(s), {'kind': 'TOOL_CALL', 'tool': 'apply_a'})['atoms']
    got = evaluate_atom(s, atom, target(s))
    assert got['value'] == ('FALSE' if parent == 'X' else 'UNRESOLVED')
    assert got['finding'] is (parent == 'X')


@pytest.mark.parametrize('quantifier', ['ANY', 'ALL'])
def test_aggregate_child_id_does_not_prove_parent_scope(quantifier):
    s = store('⟦ASSISTANT⟧\n→ TOOL_CALL inspect_b: {}\n← TOOL_RESPONSE inspect_b: '
              '{"items":{"X":{"record_id":"X","enabled":false}}}\n')
    atom = atomic(modality='REQUIRES', confirmation=None,
                  condition=comparison('state.inspect_b./items/{key}/enabled', value=True, quantifier=quantifier))
    assert evaluate_atom(s, atom, target(s))['value'] == 'UNRESOLVED'


def test_latest_contradiction_unknown_but_unrelated_read_skipped():
    first = '⟦ASSISTANT⟧\n→ TOOL_CALL inspect_b: {"record_id":"X"}\n← TOOL_RESPONSE inspect_b: {"record_id":"X","enabled":true}\n'
    a = atomic(modality='REQUIRES', confirmation=None, condition=comparison('state.inspect_b./enabled', value=True))
    conflicting = store(first + '→ TOOL_CALL inspect_b: {"record_id":"X"}\n← TOOL_RESPONSE inspect_b: {"record_id":"Y","enabled":false}\n')
    assert evaluate_atom(conflicting, a, target(conflicting))['value'] == 'UNRESOLVED'
    unrelated = store(first + '→ TOOL_CALL inspect_b: {"record_id":"Y"}\n← TOOL_RESPONSE inspect_b: {"record_id":"Y","enabled":false}\n')
    assert evaluate_atom(unrelated, a, target(unrelated))['value'] == 'TRUE'


def test_user_call_cannot_be_assistant_target():
    s = store(response='⟦USER⟧\n→ TOOL_CALL apply_a: {"record_id":"X","amount":3}')
    atom = atomic(modality='REQUIRES', confirmation=None, condition=comparison(value=2))
    trigger = {'kind': 'TOOL_CALL', 'tool': 'apply_a'}
    proposals = [{'proposer': str(i), 'family': str(i), 'trigger': trigger, 'response': {'atoms': [atom.model_dump()]}} for i in range(3)]
    assert not evaluate_table(s, assemble(policy(s), proposals))['decisive_error']


@pytest.mark.parametrize('actor', [None, 'USER'])
def test_time_requires_proven_observation(actor):
    extra = ('⟦' + actor + '⟧\n→ TOOL_CALL get_current_time: {}\n' if actor else '⟦ASSISTANT⟧\n')
    s = store(extra + '← TOOL_RESPONSE get_current_time: "2026-10-03T00:00:00Z"\n')
    assert current_datetime(s, target(s)).status == 'UNRESOLVED'


def test_path_null_is_not_literal_null():
    s = store('⟦ASSISTANT⟧\n→ TOOL_CALL inspect_b: {"record_id":"X"}\n← TOOL_RESPONSE inspect_b: {"record_id":"X","amount":null}\n')
    atom = atomic(modality='REQUIRES', confirmation=None, condition={'kind': 'COMPARE', 'lhs': 'args.amount', 'op': '==',
        'rhs': {'kind': 'PATH', 'path': 'state.inspect_b./amount'}})
    assert admit({'atoms': [atom.model_dump()]}, policy(s), {'kind': 'TOOL_CALL', 'tool': 'apply_a'})['atoms']
    assert evaluate_atom(s, atom, target(s))['value'] == 'UNRESOLVED'


def test_identity_comparand_cannot_hide_call_result_contradiction():
    s = store('⟦ASSISTANT⟧\n→ TOOL_CALL inspect_b: {"record_id":"X"}\n'
              '← TOOL_RESPONSE inspect_b: {"record_id":"Y","amount":2}\n')
    a = atomic(modality='REQUIRES', confirmation=None, condition={'kind': 'COMPARE', 'lhs': 'args.record_id',
        'op': '==', 'rhs': {'kind': 'PATH', 'path': 'state.inspect_b./record_id'}})
    assert admit({'atoms': [a.model_dump()]}, policy(s), {'kind': 'TOOL_CALL', 'tool': 'apply_a'})['atoms']
    got = evaluate_atom(s, a, target(s))
    assert got['value'] == 'UNRESOLVED' and not got['finding']


def test_agreement_never_rounds_large_numbers_or_depends_on_decimal_context():
    s = store(); p = policy(s); trigger = {'kind': 'TOOL_CALL', 'tool': 'apply_a'}
    atoms = [atomic(modality='REQUIRES', confirmation=None, condition=comparison(value=10 ** 35 + n)) for n in (1, 2, 3)]
    keys = [canonical(p['policy_sha256'], trigger, a) for a in atoms]
    assert len(set(keys)) == 3
    with localcontext() as ctx:
        ctx.prec = 5
        assert keys == [canonical(p['policy_sha256'], trigger, a) for a in atoms]
    proposals = [{'proposer': str(i), 'family': str(i), 'trigger': trigger, 'response': {'atoms': [a.model_dump()]}} for i, a in enumerate(atoms)]
    assert not assemble(p, proposals)['atoms']


@pytest.mark.parametrize('op1,op2,value1,value2', [('!=', 'not_in', None, [None]), ('==', 'in', None, [None])])
def test_null_operators_with_different_unknown_semantics_do_not_vote_together(op1, op2, value1, value2):
    s = store(); p = policy(s); trigger = {'kind': 'TOOL_CALL', 'tool': 'apply_a'}
    atoms = [atomic(modality='REQUIRES', confirmation=None, condition=comparison(op=op, value=value))
             for op, value in [(op1, value1), (op2, value2)]]
    assert canonical(p['policy_sha256'], trigger, atoms[0]) != canonical(p['policy_sha256'], trigger, atoms[1])


def test_wire_adapter_preserves_binding_and_rejects_conflicts():
    s = store(); p = policy(s); trigger = {'kind': 'TOOL_CALL', 'tool': 'apply_a'}
    raw = {'modality': 'REQUIRES_PRIOR_CALL', 'prior_call': {'tool': 'inspect_b',
           'binding': {'argument': 'record_id', 'record_field': 'record_id'}}, 'clause_ids': ['clause_0'], 'exceptions': []}
    parsed = admit({'atoms': [raw]}, p, trigger)
    assert len(parsed['atoms']) == 1 and parsed['adaptations'][0]['conversion'] == 'prior_wrapper/v1'
    assert parsed['atoms'][0]['binding']['argument'] == 'record_id'
    conflict = {**raw, 'binding': {'argument': 'amount', 'record_field': 'record_id'}}
    assert not admit({'atoms': [conflict]}, p, trigger)['atoms']
    assert not admit({'atoms': [{**raw, 'modality': 'prior_call'}]}, p, trigger)['atoms']


@pytest.mark.parametrize('literal', [None, [None]])
def test_explicit_null_survives_admission_assembly_and_verification(literal):
    s = store(); p = policy(s); trigger = {'kind': 'TOOL_CALL', 'tool': 'apply_a'}
    # Use a declared argument of the matching type; arbitrary literal JSON is not a state claim.
    field = {'type': 'null' if literal is None else 'object' if isinstance(literal, dict) else 'array', 'enum': []}
    p['catalog']['tools']['apply_a']['arguments']['amount'] = field
    p['catalog']['paths']['args.amount'] = [field['type']]
    atom = atomic(modality='REQUIRES', confirmation=None, condition=comparison(value=literal))
    parsed = admit({'atoms': [atom.model_dump()]}, p, trigger)
    assert parsed['atoms'][0]['condition']['rhs']['value'] == literal
    proposals = [{'proposer': str(i), 'family': str(i), 'trigger': trigger,
                  'response': {'atoms': [atom.model_dump()]}} for i in range(3)]
    table = assemble(p, proposals)
    from guardian_truth.policy_table_v11.compile import verify_table
    verify_table(table)
    assert table['atoms'][0]['atom']['condition']['rhs']['value'] == literal
