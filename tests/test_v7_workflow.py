import copy
from scripts.v7_workflow_data import make_pair,oracle,DOMAINS,FAMILIES
from scripts.v4_freeze_data import audit

def test_all_labels_recomputed_without_gold_and_negative_schema():
    for d in DOMAINS:
        for f in FAMILIES:
            for v in range(8):
                pair=make_pair(d,f,v,'0'*40)
                for r in pair:
                    expected=r.pop('label');r.pop('rationale')
                    assert oracle(r)[0]==expected
                    r['label']=expected;audit(r)

def test_numeric_resource_substring_does_not_authorize_wrong_amount():
    r=make_pair('banking','consent_amount',0,'0'*40)[1]
    r['history'][4]['content']='I authorize GX7_11 at 118 units.'
    r['target_turn']['tool_calls'][0]['function']['arguments']['amount']=11
    assert oracle(r)[0]==1

def test_authorization_cannot_override_eligibility():
    good,bad=make_pair('insurance','eligibility',0,'0'*40)
    assert good['history'][4]==bad['history'][4]
    assert oracle(good)[0]==0 and oracle(bad)[0]==1

def test_amount_mutation_does_not_rename_resource():
    for v in range(80):
        good,bad=make_pair('telecom','consent_amount',v,'0'*40)
        assert good['proof']['resource_id'] in bad['history'][4]['content']
