import copy
import pytest
from scripts.v7_train import validate_resume
from scripts.v5_35b_common import BASE_REVISION

def test_resume_preserves_frozen_order_and_committed_batch_boundary():
    receipt=dict(data_sha256='same',base_revision=BASE_REVISION,layers=16,rows_done=16,steps=2)
    order=list(map(str,range(32)));state=dict(order=order,rows_done=16,steps=2)
    validate_resume(receipt,state,'same',16,order)
    with pytest.raises(ValueError,match='PROFILE_DRIFT'):validate_resume(receipt,state,'different',16,order)
    with pytest.raises(ValueError,match='PROFILE_DRIFT'):validate_resume(receipt,state,'same',8,order)
    with pytest.raises(ValueError,match='ORDER'):validate_resume(receipt,state,'same',16,list(reversed(order)))
    corrupt=copy.deepcopy(state);corrupt['rows_done']=17
    with pytest.raises(ValueError):validate_resume(receipt,corrupt,'same',16,order)

def test_resume_rejects_uncommitted_partial_batch_even_with_matching_receipt():
    receipt=dict(data_sha256='same',base_revision=BASE_REVISION,layers=16,rows_done=17,steps=2)
    order=list(map(str,range(32)));state=dict(order=order,rows_done=17,steps=2)
    with pytest.raises(ValueError,match='BATCH_BOUNDARY'):validate_resume(receipt,state,'same',16,order)
