import pytest
from guardian_truth.policy_table.compile import assemble, request
from test_policy_table_eval import source, rule


def test_three_samples_decisive_two_shadow_duplicates_not_extra_votes():
    store = source(False)
    a = {'rules': [rule().model_dump()], 'uncovered_clause_ids': []}
    b = {'rules': [], 'uncovered_clause_ids': ['clause_0']}
    assert assemble([store], [a, a, a]).rules[0]['status'] == 'DECISIVE'
    assert assemble([store], [a, a, b]).rules[0]['status'] == 'SHADOW'
    duplicated = {'rules': [rule().model_dump(), rule().model_dump()], 'uncovered_clause_ids': []}
    assert not assemble([store], [duplicated, b, b]).rules


def test_invalid_path_type_or_trigger_is_discarded():
    store = source(False)
    for r in (rule(conditions=[{'lhs': 'state.tool_b./missing', 'op': '==', 'rhs': {'kind': 'LITERAL', 'value': True}}]),
              rule(conditions=[{'lhs': 'state.tool_b./field_y', 'op': '<', 'rhs': {'kind': 'LITERAL', 'value': 1}}]),
              rule(trigger={'kind': 'TOOL_CALL', 'tool': 'tool_unknown'})):
        a = {'rules': [r.model_dump()], 'uncovered_clause_ids': []}
        table = assemble([store], [a, a, a])
        assert not table.rules
        assert table.discarded


def test_compiler_uses_wire_enums_and_different_sample_requests():
    import json
    store = source(False)
    a, b = request([store], 0), request([store], 1)
    assert a != b
    packet = json.loads(a[1]['content'])
    assert packet['schema']['$defs']['KnownPath']['enum']
    assert packet['clauses']


def test_independent_system_hash_and_three_samples_required():
    with pytest.raises(ValueError): assemble([source()], [])


def test_cache_cannot_upgrade_two_samples_to_decisive(tmp_path):
    import json
    from guardian_truth.policy_table.evaluate import load_table
    store = source(False)
    a = {'rules': [rule().model_dump()], 'uncovered_clause_ids': []}
    b = {'rules': [], 'uncovered_clause_ids': ['clause_0']}
    table = assemble([store], [a, a, b])
    path = tmp_path / (table.policy_sha256 + '.json')
    path.write_text(table.model_dump_json(), encoding='utf-8')
    assert load_table(store, tmp_path).rules[0]['status'] == 'SHADOW'
    corrupt = table.model_dump(); corrupt['rules'][0].update(status='DECISIVE', agreement=3)
    path.write_text(json.dumps(corrupt), encoding='utf-8')
    with pytest.raises(ValueError): load_table(store, tmp_path)


def test_numeric_literal_canonicalization_preserves_opaque_strings_and_booleans():
    from guardian_truth.policy_table.compile import canonical
    def item(value):
        return rule(conditions=[{'lhs': 'args.field_x', 'op': '==', 'rhs': {'kind': 'LITERAL', 'value': value}}])
    assert canonical(item(1)) == canonical(item(1.0))
    assert canonical(item(1)) != canonical(item(True))
    assert canonical(item('01')) != canonical(item('1'))
