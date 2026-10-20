import pytest
from scripts.v12_offbox_report import replay_arm,wire,metric


def test_unknown_never_vetoes_and_requires_actual_review_call_receipt():
    inputs=[dict(id='x',position=2,oversized=False,ids=[1,2],source_policy='Some real and sufficiently long policy clause.',input_sha256='a')]
    records=[dict(id='x',position=2,input_sha256='a',review='bad format',admitted=False,status='INVALID_FORMAT',source_support=None,score=None,exact=False)]
    audit=[dict(max_tokens=192,inputs_sha256=wire([dict(prompt_token_ids=[1,2])]),prompts=1,outputs=1)]
    assert replay_arm(inputs,records,None,audit)=={2:True}
    audit[0]['inputs_sha256']='wrong'
    with pytest.raises(ValueError,match='GENERATION_INPUT'):replay_arm(inputs,records,None,audit)


def test_metrics_keep_false_negatives_visible():
    assert metric([dict(label=1),dict(label=0)],[0,0])['fn']==1
