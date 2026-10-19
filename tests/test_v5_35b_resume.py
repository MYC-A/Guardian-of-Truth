import copy
import random
import pytest
from scripts.v5_35b_common import BASE_REVISION
from scripts.v5_35b_resume import validate_resume


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
