"""Provider truncation and original-format fixture boundary regressions."""
import pytest

from experiments.whole_move_v1 import fixtures
from experiments.whole_move_v1.runner import decode_whole, full_packet
from experiments.whole_move_v1.reviewer import body


@pytest.mark.parametrize('finish', ['length','tool_calls',None])
def test_nonfinal_provider_reply_cannot_be_admitted(finish):
    rec=dict(status='OK',provider_response=dict(choices=[dict(finish_reason=finish,
        message=dict(content='{"target_reviews":[]}'))]))
    assert decode_whole(rec,None,{})['failure']=='INVALID_OR_UNFINISHED_JSON'


@pytest.mark.parametrize('data', [None,{},dict(choices=[]),dict(choices=[{}])])
def test_provider_shape_is_explicit_technical_failure(data):
    assert decode_whole(dict(status='OK',provider_response=data),None,{})['failure']=='PROVIDER_SHAPE_INVALID'


def test_all_fresh_cases_traverse_original_parser_and_have_no_gold_request_fields():
    inputs=fixtures.build(extended=True);gold=fixtures.gold(extended=True)
    assert len(inputs)==12 and {r['id'] for r in inputs}==set(gold)
    for row in inputs:
        assert set(row)=={'id','prompt','response'}
        packet=full_packet(row)
        assert packet['coverage']['complete_input'] is True
        assert packet['current_targets']
        req=body(packet,'mistral','test-model')
        assert req['max_tokens']==3600
        assert req['messages'][1]['content']
        assert 'expected_cause' not in req['messages'][1]['content']
        assert 'binary_projection' not in req['messages'][1]['content']
