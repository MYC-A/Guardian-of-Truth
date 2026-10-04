"""Real source boundaries/native joins/unknown propagation, not model-quality tests."""
from copy import deepcopy
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'experiments/research_v3'))
from build_suite import build
from contracts import Direct
from pilot import admit, lower_tree, make_graph, native_check, registry, packet


def setup(variant='allowed'):
    rows, _ = build()
    row = next(r for r in rows if r['id'] == 'custody.' + variant)
    g = make_graph(row)
    return g, registry(row, g)


def check(reg, graph):
    sid = next(sid for sid, s in reg['sources'].items() if s['kind'] == 'result')
    lid = next(k for k, v in reg['policy_literals'].items() if v['value'] is True)
    return dict(lhs_source=sid, lhs_pointer='/authorized', operator='==', rhs_source=None,
                rhs_pointer=None, literal_id=lid,
                bindings=[{'target_pointer': '/asset_id', 'source_pointer': '/asset_id'},
                          {'target_pointer': '/new_owner_id', 'source_pointer': '/new_owner_id'}])


def test_family_split_and_gold_are_disjoint_and_inputs_do_not_embed_answers():
    rows, gold = build()
    assert len(rows) == 32
    dev = {g['family'] for g in gold.values() if g['split'] == 'dev'}
    heldout = {g['family'] for g in gold.values() if g['split'] == 'heldout'}
    assert not dev & heldout
    assert all(set(r) == {'id', 'prompt', 'response', 'policy_sections'} for r in rows)


def test_forward_discovery_packet_hides_target_history_case_split_gold():
    g, reg = setup()
    p = packet(reg, target=False)
    assert 'target' not in p and 'target_id' not in p
    assert all(s['kind'] in ('policy', 'declaration') for s in p['sources'].values())
    assert 'custody' not in str(p) and 'dev' not in p


def test_source_id_admission_rejects_real_wrong_role_and_nonexistent_id():
    _, reg = setup()
    r = dict(verdict='ERROR', effect='MODIFY', applies='YES', policy_ids=['p0'],
             evidence_ids=[], missing=[], reason='test interpretation')
    assert admit(Direct, r, reg)
    r['policy_ids'] = [reg['target_id']]
    with pytest.raises(ValueError, match='WRONG_ROLE'):
        admit(Direct, r, reg)
    r['policy_ids'] = ['p999']
    with pytest.raises(ValueError, match='UNKNOWN_SOURCE'):
        admit(Direct, r, reg)


def test_native_bool_result_is_checked_and_wrong_parent_becomes_unknown():
    g, reg = setup()
    assert native_check(check(reg, g), g, reg)['value'] == 'TRUE'
    g, reg = setup('identity')
    assert native_check(check(reg, g), g, reg)['value'] == 'UNKNOWN'


def test_negative_native_observation_is_false_not_unknown():
    g, reg = setup('negative')
    assert native_check(check(reg, g), g, reg)['value'] == 'FALSE'


def test_later_receipt_cannot_authorize_first_target():
    g, reg = setup('chronology')
    assert native_check(check(reg, g), g, reg)['value'] == 'UNKNOWN'


def test_empty_or_temporal_wrong_arity_cannot_be_lowered():
    _, reg = setup()
    for op in ('AND', 'BEFORE'):
        with pytest.raises(ValueError, match='arity'):
            lower_tree(dict(op=op, label='test', source_ids=['p0'], children=[]), reg)


def test_native_sources_cannot_stand_in_for_policy_tree():
    _, reg = setup()
    with pytest.raises(ValueError, match='NON_POLICY'):
        lower_tree(dict(op='ATOM', label='test', source_ids=[reg['target_id']], children=[]), reg)
