import json
import pytest
from scripts.v8_quote_contract import quote_support,admit_review,decoded_units

def policy(value):return '<policy>\n'+json.dumps(value,ensure_ascii=True,indent=2)+'\n</policy>'

def test_json_key_and_decoded_value_have_a_source_path():
    p=policy({'Intent':{'Phase 4':"Verify profile: Ask for the caller’s full name."}})
    q="Phase 4: Verify profile: Ask for the caller’s full name."
    assert q not in p
    proof=quote_support(q,p)
    assert proof['path']=='/Intent/Phase 4' and proof['kind']=='STRUCTURED_JSON_SOURCE'

@pytest.mark.parametrize('wrong',[
    'Phase 5: Verify profile before releasing 20 units.',
    'Phase 4: Verify profile before releasing 200 units.',
    'Phase 4: Do not verify profile before releasing 20 units.',
    'Phase 4: Verify profile before releasing 20 dollars.',
])
def test_wrong_phase_number_amount_negation_or_unit_is_not_a_quote(wrong):
    assert quote_support(wrong,policy({'Phase 4':'Verify profile before releasing 20 units.'})) is None

def test_whitespace_match_retains_original_source_span():
    p='Rule: Before payment,\n    obtain explicit authorization.'
    q='Before payment, obtain explicit authorization.'
    proof=quote_support(q,p)
    assert proof['kind']=='RAW_WHITESPACE_ONLY'
    assert ' '.join(p[slice(*proof['span'])].split())==q

def test_no_arbitrary_join_across_json_properties():
    p=policy({'Phase 4':'Obtain authorization.','Phase 5':'Execute the request.'})
    assert quote_support('Phase 4: Obtain authorization. Execute the request.',p) is None

def test_duplicate_keys_do_not_produce_decoded_source_proof():
    p='<policy>{"Phase 4":"Original instruction.","Phase 4":"Different instruction."}</policy>'
    assert decoded_units(p)==[]
    assert quote_support('Phase 4: Different instruction.',p) is None

def test_truncated_or_unknown_review_cannot_veto_even_with_valid_source():
    p=policy({'Phase 4':'Obtain explicit authorization.'})
    text='Rule: Phase 4: Obtain explicit authorization.\nEvidence: UNKNOWN whether authorization was given.'
    assert admit_review(text,p)[1]=='UNKNOWN'
    assert admit_review(text,p,True)[1]=='TRUNCATED'

def test_literal_compatibility_and_partial_decoded_quote():
    q='Only apply the authorized change.'
    assert quote_support(q,q)['kind']=='RAW_LITERAL'
    q='Only apply the user\u2019s authorized change.'
    assert quote_support('apply the user\u2019s authorized change.',policy({'Rule':q}))['kind']=='STRUCTURED_JSON_SOURCE'
