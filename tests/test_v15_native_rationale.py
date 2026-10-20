import copy
import json
import pytest
from scripts.v15_native_rationale import visible_evidence
from scripts.v7_train import validate_recipe,validate_verdict_token


def test_evidence_cannot_read_future_execution_mutation_proof_or_label():
    row=dict(family='order_status',domain='retail',history=[dict(role='tool',name='get_order_details',content=json.dumps(dict(status='pending')))],
        target_turn=dict(tool_calls=[dict(function=dict(name='cancel_pending_order',arguments={}))]),
        label=0,proof=dict(native_target_execution=dict(results=['SECRET_FUTURE']),predicate=dict(bad_status='delivered')))
    first=visible_evidence(row);changed=copy.deepcopy(row);changed['label']=1;changed['proof']={'anything':'DIFFERENT_FUTURE'}
    assert visible_evidence(changed)==first
    assert 'pending' in first and 'SECRET_FUTURE' not in first and 'delivered' not in first
    changed['history'][0]['content']=json.dumps(dict(status='delivered'))
    assert visible_evidence(changed)!=first


def test_native_training_requires_full_balanced_unique_pairs_and_fixed_replay():
    records=[dict(id=f'{i}:{label}',pair_id=str(i),label=label,objective='sft',answer_ids=[10 if label else 11]) for i in range(40) for label in (0,1)]
    records+=[dict(id='replay:'+str(i),objective='bce') for i in range(32)]
    meta=dict(recipe='V15_NATIVE_RATIONALE_V1',sft_rows=80,verdict_bce_weight=.5,answer_ids=dict(yes=[10],no=[11]))
    validate_recipe(records,meta,True)
    records[0]['label']=1
    with pytest.raises(ValueError,match='COMPLETE_PAIRS'):validate_recipe(records,meta,True)
    records[0]['label']=0;records[-1]['id']=records[0]['id']
    with pytest.raises(ValueError,match='FROZEN_NATIVE_RECIPE'):validate_recipe(records,meta,True)


def test_teacher_verdict_boundary_cannot_flip_class_or_score_eos():
    answers=dict(yes=[10],no=[11])
    validate_verdict_token([2,3,10],1,answers)
    for answer,label in [([2,3,10],0),([2,3,11,0],0),([],1)]:
        with pytest.raises(ValueError,match='BOUNDARY'):validate_verdict_token(answer,label,answers)


@pytest.mark.parametrize('compact,sft,bce,recipe',[(False,80,32,'V17_NATIVE_BUDGET_RATIONALE_V1'),(True,64,16,'V18_NATIVE_COMPACT_RATIONALE_V1')])
def test_budget_recipe_cannot_masquerade_as_original_v15_or_remove_replay(compact,sft,bce,recipe):
    records=[dict(id=f'{i}:{label}',pair_id=str(i),label=label,objective='sft',answer_ids=[10 if label else 11]) for i in range(sft//2) for label in (0,1)]
    records+=[dict(id='replay:'+str(i),objective='bce') for i in range(bce)]
    meta=dict(recipe=recipe,sft_rows=sft,selected_native_fp=8,
        original_v15_sixteen_error_gate_passed=False,verdict_bce_weight=.5,answer_ids=dict(yes=[10],no=[11]))
    validate_recipe(records,meta,True,True,compact)
    with pytest.raises(ValueError,match='FROZEN_NATIVE_RECIPE'):validate_recipe(records,meta,True)
    with pytest.raises(ValueError,match='FROZEN_NATIVE_RECIPE'):validate_recipe(records[:-1],meta,True,True,compact)
    meta['selected_native_fp']=7
    with pytest.raises(ValueError,match='BUDGET_NATIVE_RECIPE'):validate_recipe(records,meta,True,True,compact)


def test_failure_recovery_keeps_latest_committed_optimizer_checkpoint(tmp_path):
    import tarfile
    from types import SimpleNamespace
    from scripts.v15_controller import recovery
    trained=tmp_path/'training-v1/layers16'
    for number in (1,2):
        p=trained/f'checkpoint-{number:03d}';p.mkdir(parents=True)
        (p/'CHECKPOINT.json').write_text('{}')
        (p/'state.pt').write_bytes(b'optimizer-rng-order-'+bytes([number]))
    recovery(SimpleNamespace(out=tmp_path),trained)
    with tarfile.open(tmp_path/'final-recovery-export.tar.gz') as t:
        assert t.extractfile('training-v1/layers16/checkpoint-002/state.pt').read().endswith(b'\x02')
        assert all('checkpoint-001' not in n for n in t.getnames())
