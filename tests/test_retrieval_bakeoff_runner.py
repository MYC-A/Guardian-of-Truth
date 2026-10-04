import pytest
from experiments.retrieval_bakeoff_v1.runner import decode

@pytest.mark.parametrize('data',[{}, {'choices':None},{'choices':[]},{'choices':[None]},
    {'choices':[{}]},{'choices':[{'message':None}]},{'choices':[{},{}]}])
def test_provider_shape_is_technical_null_not_crash_or_binary_zero(data):
    result=decode(dict(status='OK',provider_response=data),None,{})
    assert result==dict(decision=None,raw_decision=None,failure='PROVIDER_SHAPE_INVALID')

def test_http_failure_never_becomes_semantic_unknown():
    assert decode(None,'HTTP_ERROR',{})==dict(decision=None,raw_decision=None,failure='HTTP_ERROR')

def test_nonobject_raw_reply_is_not_a_semantic_label():
    result=decode(dict(status='OK',provider_response={'choices':[{'finish_reason':'stop','message':{'content':'[]'}}]}),None,{})
    assert result['decision'] is None and result['failure'].startswith('ADMISSION:')
