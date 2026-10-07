import json
import pytest
from experiments.guardian_local_a100 import granite_native as g


def test_native_complete_score_with_budget_boundary_is_usable():
    assert g.parse('<think>\n</think>\n<score> yes </score>')==1
    assert g.parse('<score> no </score><|end_of_text|>')==0
    for bad in ('<score>yes','<score>yesterday</score>','<score>yes</score><score>no</score>',
                '<think>maybe</think><score>yes</score>','Reason: yes','<score>no</score> extra'):
        assert g.parse(bad) is None


def test_native_request_preserves_historical_field_bounds_and_polarity():
    class Tokenizer:
        def apply_chat_template(self,messages,**kw):
            assert kw['guardian_config']=={'criteria_id':'groundedness'}
            assert kw['think'] is False and kw['add_generation_prompt'] is True
            assert messages==[{'role':'assistant','content':'Current move.'}]
            assert kw['documents'][0]['doc_id']=='prompt_context'
            return kw['documents'][0]['text']
    text,meta=g.request(Tokenizer(),dict(prompt='A'*6000+'TAIL',response='Current move.'))
    assert len(text)==4800 and text.endswith('TAIL')
    assert meta['prompt']['truncated'] and not meta['complete_input']
    assert meta['response']['text']=='Current move.'


def test_missing_model_decision_never_becomes_negative():
    assert g.combine(0,None,'OR') is None
    assert g.combine(1,None,'OR')==1
    assert g.combine(1,None,'AND') is None
    assert g.combine(0,None,'AND')==0
    report=g.score_predictions({'x':None},{'x':0},{'x':1},{'x':1})
    assert report['granite_new']['unavailable_positive']==1
    assert report['combinations']['fresh_OR']['unavailable_positive']==1
    with pytest.raises(ValueError,match='UNMATCHED'):
        g.score_predictions({}, {'x':0},{'x':1},{'x':1})


def test_checkpoint_mutation_cannot_reuse_declared_revision(tmp_path):
    model=tmp_path/'checkpoint';model.mkdir()
    shard=model/'model-01.safetensors';shard.write_bytes(b'expected fixture')
    (model/'model.safetensors.index.json').write_text(json.dumps({'weight_map':{'w':shard.name}}),encoding='utf-8')
    (tmp_path/'granite_download_setup.json').write_text(json.dumps(dict(repo=g.MODEL,resolved_revision=g.REVISION,
        expected_weights={shard.name:dict(sha256=g.file_digest(shard),size=shard.stat().st_size)})),encoding='utf-8')
    assert g.verify_checkpoint(model)[shard.name]==g.file_digest(shard)
    shard.write_bytes(b'changed checkpoint')
    with pytest.raises(ValueError,match='WEIGHT_HASH'):
        g.verify_checkpoint(model)
