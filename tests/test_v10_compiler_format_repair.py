"""The observed transport-shape failure can be repaired without changing logic."""
import importlib.util
from pathlib import Path
import sys
import pytest

DIRECTORY = Path(__file__).resolve().parents[1] / 'experiments/searh_23/source_search_20261002'
sys.path.insert(0, str(DIRECTORY))
spec = importlib.util.spec_from_file_location('resume', DIRECTORY / 'compile_tables_v10_resume.py')
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)


def wire(lhs):
    return {'rules': [{'rule_id': 'r', 'clause_ids': ['p'], 'trigger': {'kind': 'TOOL_CALL', 'tool': 'tool_a', 'act': None},
        'modality': 'REQUIRES', 'conditions': [{'lhs': lhs, 'op': '==', 'rhs': {'kind': 'LITERAL', 'value': True}}],
        'exceptions': [], 'prior_call': None, 'compile_status': 'COMPILED', 'not_compilable_reason': None}], 'uncovered_clause_ids': []}


def test_exact_path_wrapper_is_lossless_and_input_is_immutable():
    original = wire({'kind': 'PATH', 'path': 'state.tool_a./field_x'})
    normalized, repairs = module.parse_wire(original)
    expected, no_repairs = module.parse_wire(wire('state.tool_a./field_x'))
    assert normalized == expected and no_repairs == [] and len(repairs) == 1
    assert isinstance(original['rules'][0]['conditions'][0]['lhs'], dict)


@pytest.mark.parametrize('lhs', [{'kind': 'LITERAL', 'path': 'args.field_x'},
    {'kind': 'PATH', 'path': 'args.field_x', 'negated': True}, {'kind': 'PATH', 'path': 1}, {'path': 'args.field_x'}])
def test_any_semantic_or_ambiguous_wrapper_is_rejected(lhs):
    with pytest.raises(ValueError): module.parse_wire(wire(lhs))


def test_repair_does_not_admit_unknown_rhs_or_missing_schema_fields():
    bad = wire({'kind': 'PATH', 'path': 'args.field_x'})
    bad['rules'][0]['conditions'][0]['rhs'] = {'kind': 'OTHER', 'value': True}
    with pytest.raises(ValueError): module.parse_wire(bad)
    del bad['rules'][0]['exceptions']
    with pytest.raises(ValueError): module.parse_wire(bad)


def test_partial_admission_discards_invalid_rules_without_guessing_them():
    sample = wire('args.field_x')
    import copy
    invalid = copy.deepcopy(sample['rules'][0])
    invalid['trigger']['tool'] = None
    sample['rules'].append(invalid)
    admitted, receipts = module.parse_wire(sample, allow_partial=True)
    assert admitted['rules'] == sample['rules'][:1]
    assert receipts[0]['operation'] == 'REJECT_SCHEMA_INVALID_CANDIDATE'
    assert sample['rules'][1]['trigger']['tool'] is None


def test_partial_admission_does_not_repair_envelope_or_empty_requirements():
    sample = wire('args.field_x'); sample['rules'][0]['conditions'] = []
    admitted, receipts = module.parse_wire(sample, allow_partial=True)
    assert admitted['rules'] == [] and len(receipts) == 1
    sample['invented_field'] = True
    with pytest.raises(ValueError): module.parse_wire(sample, allow_partial=True)
