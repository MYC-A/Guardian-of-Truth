import copy
import pytest

from guardian_truth.policy_table_v11 import consent_pair_v3 as c
from test_policy_table_v11_consent_pair_v2 import fixture, response


def evidence(data):
    data = copy.deepcopy(data)
    kind = data.pop('kind')
    for plan in data['plans']:
        plan['kind'] = kind
        supports = {b['path']: b['span_ids'] for b in plan.pop('bindings')}
        args = plan.pop('arguments')
        plan['parameters'] = {k: {'value': v, 'span_ids': supports['/' + k]} for k, v in args.items()}
    return data


def test_supported_values_generate_arguments_and_pointer_inventory():
    s, t = fixture()
    data = evidence(response(s, t))
    admitted = c.admit(data, s, t)
    assert admitted['plans'][0]['arguments'] == {'record_id': 'X', 'amount': 2}
    assert c.verdict(admitted, s, t)['value'] == 'TRUE'


def test_nested_arrays_preserve_parent_child_identity_order_and_types():
    tree = {'owner/id': {'value': 'P', 'span_ids': ['s1']}, 'passengers': [
        {'id': {'value': 'A', 'span_ids': ['s2']}, 'seat': {'value': '1A', 'span_ids': ['s2']}},
        {'id': {'value': 'B', 'span_ids': ['s3']}, 'seat': {'value': '1B', 'span_ids': ['s3']}}]}
    args, bindings = c.unpack(tree)
    assert args == {'owner/id': 'P', 'passengers': [{'id': 'A', 'seat': '1A'}, {'id': 'B', 'seat': '1B'}]}
    assert [b['path'] for b in bindings] == ['/owner~1id', '/passengers/0/id', '/passengers/0/seat', '/passengers/1/id', '/passengers/1/seat']
    assert c.unpack({'a': {'value': True, 'span_ids': ['s1']}})[0]['a'] is True


@pytest.mark.parametrize('node', [2, [], {}, {'value': 2, 'span_ids': []},
                                {'value': [2, 3], 'span_ids': ['s1']},
                                {'value': {'a': 2}, 'span_ids': ['s1']}])
def test_bare_values_and_container_shortcuts_are_rejected(node):
    with pytest.raises(ValueError):
        c.unpack(node)


def test_invalid_tree_cannot_be_silently_dropped():
    s, t = fixture()
    data = evidence(response(s, t))
    data['plans'][0]['parameters']['amount'] = 2
    result = c.admit(data, s, t)
    assert result['tree_failures']
    assert c.verdict(result, s, t)['value'] == 'UNRESOLVED'


def test_classification_is_per_operation_and_user_executor_is_rejected():
    s, t = fixture()
    data = evidence(response(s, t))
    other = copy.deepcopy(data['plans'][0])
    other.update(tool='inspect_b', kind='CONDITIONAL')
    data['plans'].append(other)
    assert c.verdict(c.admit(data, s, t), s, t)['value'] == 'TRUE'
    data['plans'][0]['actor'] = 'USER'
    assert c.verdict(c.admit(data, s, t), s, t)['value'] == 'UNRESOLVED'


@pytest.mark.parametrize('tool', [[], {}, 42, 'undeclared_operation'])
def test_unidentifiable_rejected_plan_cannot_be_assumed_unrelated(tool):
    s, t = fixture()
    data = evidence(response(s, t))
    data['plans'].append({'tool': tool})
    admitted = c.admit(data, s, t)
    assert admitted['discarded'][0]['tool'] is None
    assert c.verdict(admitted, s, t)['value'] == 'UNRESOLVED'


def test_target_values_still_hidden_and_source_binding_is_not_relaxed():
    s, t = fixture(amount=999)
    data = evidence(response(s, t))
    assert '999' not in str(c.packet(s, t))
    assert c.verdict(c.admit(data, s, t), s, t)['value'] == 'UNRESOLVED'
    data['plans'][0]['parameters']['amount'] = {'value': 999, 'span_ids': ['h2.s0']}
    assert c.verdict(c.admit(data, s, t), s, t)['value'] == 'UNRESOLVED'
