"""Freeze-driven regressions for the reviewed-rule composition boundary."""
import importlib.util
import json
from pathlib import Path

BASE=Path(__file__).resolve().parents[1]/'experiments/searh_23/integration_v1'


def load(name):
    spec=importlib.util.spec_from_file_location(name,BASE/(name+'.py'))
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frozen_time_entity_amount_and_authority_controls():
    runner=load('run_runtime_controls')
    rows=json.loads((BASE/'frozen/runtime_controls.json').read_text(encoding='utf-8'))
    rows+=json.loads((BASE/'frozen/runtime_scope_extra.json').read_text(encoding='utf-8'))
    assert len(rows)==18
    failures=[r['id'] for r in rows if not runner.scenario(r)['passed']]
    assert not failures, failures


def test_strict_score_requires_predicate_and_strength_not_just_a_real_path():
    scorer=load('strict_step2_score')
    gold={'predicate':'item.status','entity_type':'item','entity_id':'I-7',
          'value':'"pending"','truth':'TRUE','strength':'REQUESTED',
          'provenance':{'call_id':'c1','json_path':'$.status'}}
    assert scorer.maximum_matches([gold],[gold])==1
    assert scorer.maximum_matches([gold],[{**gold,'predicate':'item.executed'}])==0
    assert scorer.maximum_matches([gold],[{**gold,'strength':'CONFIRMED'}])==0
    assert scorer.maximum_matches([gold],[gold,gold])==1


def test_strict_score_preserves_json_types():
    scorer=load('strict_step2_score')
    assert scorer.canonical('true')!=scorer.canonical('1')
    assert scorer.canonical('"5"')!=scorer.canonical('5')
