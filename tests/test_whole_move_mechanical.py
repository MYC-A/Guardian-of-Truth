"""Production-parser inputs; names and values do not encode business rules."""
import json
import random

import pytest

from experiments.whole_move_v1.mechanical import check


def row(declarations, calls, history='', policy='Follow the given tool specification.'):
    return dict(prompt='⟦SYSTEM⟧\n' + policy + '\n[AVAILABLE TOOLS]\n' + declarations
                       + '\n⟦USER⟧\nPlease continue.\n' + history,
                response='\n'.join(calls))


def call(name, value, actor='ASSISTANT'):
    return f'⟦{actor}⟧\n→ TOOL_CALL {name}: ' + json.dumps(value)


def codes(result):
    return {f['code'] for f in result['findings']}


def assert_refs_original(result, source):
    for finding in result['findings'] + result['gaps']:
        assert finding['target_id'] in {t['target_id'] for t in result['targets']}
        assert finding['source_refs']
        for ref in finding['source_refs']:
            assert source[ref['document']][ref['start']:ref['end']] == ref['text']


def test_all_calls_and_random_names_required_after_first_target():
    rng = random.Random(1005)
    for _ in range(8):
        name = 'op_' + str(rng.randrange(10**8))
        field = 'key_' + str(rng.randrange(10**8))
        r = row(f'- {name} — An operation.\n    {field}: string! — An explicit field.\n',
                [call(name, {field: 'present'}), call(name, {})])
        result = check(r)
        assert len(result['targets']) == 2
        assert result['coverage']['schema_checked_calls'] == 2
        assert len(result['findings']) == 1
        assert result['findings'][0]['target_id'] == result['targets'][1]['target_id']
        assert result['findings'][0]['path'] == '$.' + field
        assert codes(result) == {'missing_argument'}
        assert_refs_original(result, r)


def test_user_and_historical_calls_excluded():
    decl = '- inspect_alpha — An operation.\n    required: integer!\n'
    r = row(decl, [call('inspect_alpha', {'required': 2}), call('inspect_alpha', {}, actor='USER')],
            history=call('inspect_alpha', {}) + '\n')
    result = check(r)
    assert len(result['targets']) == 1 and not result['findings']
    assert result['coverage']['whole_move_certified'] is False


def test_nested_object_array_paths_and_structural_types():
    declaration = ('- nested_test — Operation.\n'
                   '    records: array!\n'
                   '        · identity: string!\n'
                   '        · details: object!\n'
                   '            amount: number!\n')
    r = row(declaration, [call('nested_test', {'records': [
        {'identity': 'x', 'details': {'amount': True}}, {'details': {}}, 'scalar']})])
    result = check(r)
    found = {(f['code'], f['path']) for f in result['findings']}
    assert found == {('argument_type', '$.records[0].details.amount'),
                     ('missing_argument', '$.records[1].identity'),
                     ('missing_argument', '$.records[1].details.amount'),
                     ('argument_type', '$.records[2]')}
    assert_refs_original(result, r)


@pytest.mark.parametrize('kind,value', [('integer', True), ('number', False), ('boolean', 1),
                                        ('string', 5), ('object', []), ('array', {})])
def test_explicit_primitive_type_mismatch(kind, value):
    result = check(row(f'- type_probe — Operation.\n    value: {kind}!\n',
                       [call('type_probe', {'value': value})]))
    assert codes(result) == {'argument_type'}


def test_enum_exact_not_substring_and_typed_numeric_choices():
    declaration = ('- enum_probe — Operation.\n'
                   '    mode: string [enum: ready|done]\n'
                   '    count: number [enum: 1|2]\n'
                   '    allowed: boolean [enum: true|false]\n')
    good = check(row(declaration, [call('enum_probe', {'mode': 'ready', 'count': 1.0, 'allowed': True})]))
    assert not good['findings'] and not good['gaps']
    bad = check(row(declaration, [call('enum_probe', {'mode': 'ready-more', 'count': 3, 'allowed': 1})]))
    assert {(f['code'], f['path']) for f in bad['findings']} == {
        ('argument_enum', '$.mode'), ('argument_enum', '$.count'), ('argument_type', '$.allowed')}


@pytest.mark.parametrize('unsupported', ['    duration: date!\n', '    value: string or null\n',
                                         '    value: string [nullable]\n', '    note: arbitrary!\n',
                                         '    unparsed schema line\n'])
def test_unknown_schema_lines_do_not_infer_known_field_absence(unsupported):
    declaration = '- partial_probe — Operation.\n    required: string!\n' + unsupported
    result = check(row(declaration, [call('partial_probe', {})]))
    assert not result['findings']
    assert any(g['code'] == 'tool_schema_not_fully_understood' for g in result['gaps'])
    assert not result['catalog']['executable_inventory_complete']


def test_unrelated_partial_tool_does_not_erase_explicit_positive_requirement():
    declaration = ('- known_probe — Operation.\n    value: string!\n'
                   '- partial_probe — Operation.\n    other: exotic!\n')
    result = check(row(declaration, [call('known_probe', {})]))
    assert codes(result) == {'missing_argument'}
    assert not result['catalog']['executable_inventory_complete']


@pytest.mark.parametrize('declaration', [
    '- duplicate_probe — First.\n    value: string!\n- duplicate_probe — Second.\n    other: number!\n',
    '- duplicate_probe — First.\n    value: string!\n    value: number!\n',
    '- duplicate_probe — First.\n    value: string!\n        child: string!\n',
])
def test_duplicate_or_ambiguous_schema_unknown(declaration):
    result = check(row(declaration, [call('duplicate_probe', {})]))
    assert not result['findings'] and result['gaps']
    assert result['coverage']['status'] == 'PARTIAL'


def test_multiple_catalogs_unknown_even_in_same_system_event():
    declaration = ('- first_probe — First.\n    value: string!\n'
                   '[AVAILABLE TOOLS]\n- second_probe — Second.\n    other: number!\n')
    result = check(row(declaration, [call('first_probe', {})]))
    assert not result['findings']
    assert not result['catalog']['authoritative']


def test_missing_or_incomplete_catalog_never_establishes_unavailability():
    absent = dict(prompt='⟦SYSTEM⟧\nSome rules.\n⟦USER⟧\nContinue.', response=call('new_probe', {}))
    incomplete = row('- known_probe — Partial...\n    value: string!\n', [call('new_probe', {})])
    unknown_line = row('- known_probe — Known.\n    value: string!\nunknown_probe: description\n',
                       [call('new_probe', {})])
    for r in (absent, incomplete, unknown_line):
        result = check(r)
        assert not result['findings']
        assert 'tool_availability_unknown' in {g['code'] for g in result['gaps']}


def test_undeclared_requires_explicit_closed_universe_and_complete_inventory():
    r = row('- known_probe — Known.\n    value: string!\n', [call('new_probe', {})])
    open_result = check(r)
    assert not open_result['findings']
    assert open_result['catalog']['executable_inventory_complete']
    assert not open_result['catalog']['tool_universe_closed']
    assert {g['code'] for g in open_result['gaps']} == {'tool_availability_unknown'}
    result = check(r, tool_universe_closed=True)
    assert result['catalog']['executable_inventory_complete']
    assert codes(result) == {'unavailable_tool'}
    assert len(result['findings'][0]['source_refs']) == 2


def test_explicit_closure_cannot_repair_partial_or_ambiguous_inventory():
    for declaration in ('- known_probe — Partial...\n    value: string!\n',
                        '- known_probe — Known.\n    value: exotic!\n',
                        '- known_probe — One.\n- known_probe — Two.\n'):
        result = check(row(declaration, [call('new_probe', {})]), tool_universe_closed=True)
        assert not result['findings'] and result['gaps']


def test_closure_premise_must_be_boolean_and_does_not_control_positive_field_rules():
    r = row('- known_probe — Known.\n    value: string!\n', [call('known_probe', {})])
    assert codes(check(r)) == codes(check(r, tool_universe_closed=True)) == {'missing_argument'}
    with pytest.raises(ValueError):
        check(r, tool_universe_closed='true')


def test_invalid_json_duplicate_keys_and_root_primitive_are_gaps():
    declaration = '- json_probe — Operation.\n    value: string!\n'
    for suffix in ('{broken', '{"value":"x","value":"y"}', '[{"value":"x"}]', 'null'):
        r = row(declaration, ['⟦ASSISTANT⟧\n→ TOOL_CALL json_probe: ' + suffix])
        result = check(r)
        assert not result['findings'] and result['gaps']


def test_call_without_parsed_name_is_gap():
    r = row('- json_probe — Operation.\n    value: string!\n', ['⟦ASSISTANT_TOOL_CALL⟧\n{}'])
    result = check(r)
    assert not result['findings']
    assert {g['code'] for g in result['gaps']} == {'call_name_unparsed'}


def test_valid_negative_extra_keys_and_optional_missing_do_not_certify_move():
    declaration = '- valid_probe — Operation.\n    value: string!\n    mode: string [enum: x|y]\n'
    r = row(declaration, [call('valid_probe', {'value': 'ok', 'extra': {'arbitrary': True}})])
    a = check(r)
    b = check(dict(r, label=1, explanation='Must not affect checker.'))
    assert a == b
    assert not a['findings'] and not a['gaps']
    assert a['coverage']['whole_move_certified'] is False
    assert 'decision' not in a


def test_prose_only_has_no_call_schema_coverage_certificate():
    r = row('- valid_probe — Operation.\n    value: string!\n',
            ['⟦ASSISTANT⟧\nI will explain the requested operation.'])
    result = check(r)
    assert result['targets'] == [] and result['findings'] == []
    assert result['coverage']['status'] == 'NO_CURRENT_ASSISTANT_CALLS'
    assert result['coverage']['whole_move_certified'] is False
