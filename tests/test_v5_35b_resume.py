import copy
import random
import pytest
from scripts.v5_35b_common import BASE_REVISION
from scripts.v5_35b_resume import validate_resume, admit_speed_probe


def fixture():
    order=list(range(1458));random.Random(20261019).shuffle(order)
    meta=dict(base_revision=BASE_REVISION,gate_sha256='gate',train_tokens_sha256='tokens',layers=8,shared=True,
        backend='AWQ_TORCH',rank=16,alpha=32,dropout=.05,learning_rate=2e-5,effective_batch=16,rows_done=480,steps=30)
    state=dict(order=order,rows_done=480,steps=30,optimizer=dict(state={i:dict(step=30) for i in range(100)}))
    return meta,state


def test_committed_resume_position_and_optimizer_are_required():
    meta,state=fixture()
    validate_resume(meta,dict(train_tokens_sha256='tokens'),state,'gate')
    for mutation in ('order','optimizer','step','recipe'):
        m,s=copy.deepcopy(meta),copy.deepcopy(state)
        if mutation=='order':s['order'][0],s['order'][1]=s['order'][1],s['order'][0]
        elif mutation=='optimizer':s['optimizer']['state'].pop(0)
        elif mutation=='step':s['optimizer']['state'][0]['step']=0
        else:m['learning_rate']=1e-4
        with pytest.raises(ValueError):validate_resume(m,dict(train_tokens_sha256='tokens'),s,'gate')


def test_numeric_admission_requires_reference_control_hard_caps_and_same_rng():
    control=dict(post_dropout_rng_equal=True,score_abs_delta=0.,loss_abs_delta=0.,gradient_relative_l2=.001,
                 worst_tensor_gradient_relative_l2=.001,max_gradient_abs_delta=1e-5)
    probe=dict(baseline_repeat_control=control,compiled_comparison=copy.deepcopy(control))
    assert admit_speed_probe(probe)
    for field,value in [('post_dropout_rng_equal',False),('score_abs_delta',.01),('gradient_relative_l2',.006),
                        ('worst_tensor_gradient_relative_l2',.03),('max_gradient_abs_delta',1e-3)]:
        bad=copy.deepcopy(probe);bad['compiled_comparison'][field]=value
        assert not admit_speed_probe(bad)
    bad=copy.deepcopy(probe);bad['baseline_repeat_control']['gradient_relative_l2']=0.
    assert not admit_speed_probe(bad)
