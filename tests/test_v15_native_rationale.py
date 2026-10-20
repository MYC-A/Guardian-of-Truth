import copy
import json
import pytest
from scripts.v15_native_rationale import visible_evidence
from scripts.v7_train import validate_recipe


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
    records=[dict(id=f'{i}:{label}',pair_id=str(i),label=label,objective='sft') for i in range(40) for label in (0,1)]
    records+=[dict(id='replay:'+str(i),objective='bce') for i in range(32)]
    meta=dict(recipe='V15_NATIVE_RATIONALE_V1',sft_rows=80)
    validate_recipe(records,meta,True)
    records[0]['label']=1
    with pytest.raises(ValueError,match='COMPLETE_PAIRS'):validate_recipe(records,meta,True)
    records[0]['label']=0;records[-1]['id']=records[0]['id']
    with pytest.raises(ValueError,match='FROZEN_NATIVE_RECIPE'):validate_recipe(records,meta,True)
