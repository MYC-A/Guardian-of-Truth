from types import SimpleNamespace
import json
import pytest
from scripts.v7_train import answer_slice
from scripts.v7_evaluate import admit_review,keep_accusation,bootstrap
from scripts.v7_mine import select
from scripts.v5_valid46_pipeline import bound_llm

def test_sft_mask_starts_at_last_prompt_position_and_excludes_last_answer_position():
    assert list(range(9))[answer_slice(9,5,4)]==[4,5,6,7]
    with pytest.raises(ValueError):answer_slice(9,6,4)

def test_review_must_quote_source_policy_and_unknown_cannot_veto():
    rule='Only apply an eligible request.'
    review='Rule: '+rule+'\nEvidence: The tool marks the request ineligible.'
    assert admit_review(review,rule,'stop')[0]
    assert not admit_review(review,'unrelated policy','stop')[0]
    assert not admit_review(review,rule,'length')[0]
    assert not admit_review('Rule: '+rule+'\nEvidence: UNKNOWN whether this applies.',rule,'stop')[0]
    assert keep_accusation(dict(admitted=False,score=None))
    assert not keep_accusation(dict(admitted=True,score=-1))
    assert keep_accusation(dict(admitted=True,score=1))

def test_binding_expected_count_is_explicit_for_sixteen_layers(tmp_path):
    class Fake:
        def __init__(self,**kwargs):pass
        def generate(self,*args,**kwargs):return ['probe']
        def collective_rpc(self,*args,**kwargs):return [dict(complete=True,expected_modules=100)]
    llm=bound_llm(Fake,object(),tmp_path/'audit.jsonl',binding_adapter=tmp_path,expected_source_modules=100)()
    assert llm.generate(['x'],SimpleNamespace(max_tokens=1))==['probe']
    llm=bound_llm(Fake,object(),tmp_path/'default.jsonl',binding_adapter=tmp_path)()
    with pytest.raises(ValueError,match='NOT_PROVEN'):llm.generate(['x'],SimpleNamespace(max_tokens=1))

def test_mining_keeps_twins_and_bounded_family_coverage():
    rows=[];scores={}
    for domain in ('a','b'):
        for family in ('x','y'):
            for variant in range(3):
                for label in (0,1):
                    key=f'{domain}:{family}:{variant}:{label}'
                    rows.append(dict(id=key,pair_id=key[:-2],domain=domain,family=family,label=label))
                    scores[key]=float(label-variant)
    chosen=select(rows,scores,count=8)
    assert len(chosen)==16
    assert all(chosen[i]['pair_id']==chosen[i+1]['pair_id'] for i in range(0,16,2))
    assert len({r['pair_id'] for r in chosen})==8

def test_group_bootstrap_uses_whole_conversation():
    rows=[dict(id='a1',original_id='a::t1'),dict(id='a2',original_id='a::t2'),dict(id='b1',original_id='b::t1')]
    result=bootstrap(rows,dict(a1=1,a2=0,b1=1),[1,1,1],[1,0,1])
    assert result['groups']==2 and result['resamples']==1000
    assert result['difference_new_minus_base_95pct']['fp'][1]<=0
