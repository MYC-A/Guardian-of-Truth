import copy
import json
import pytest
from test_policy_table_v11 import store,target
from guardian_truth.source_search.store import SourceStore
from guardian_truth.policy_table_v11 import consent_pair as c


def fixture(reply='Yes',amount=2):
    s=store('⟦ASSISTANT⟧\nI can modify record X to amount 2. Confirm?\n'+
            ('⟦USER⟧\n'+reply+'\n' if reply is not None else ''),
            response='→ TOOL_CALL apply_a: '+json.dumps({'record_id':'X','amount':amount}))
    t=target(s); sid=c.candidates(s,t)[0][0]
    events=c.timeline(s,t); uid=c.user_block(events,next(i for i,(q,_) in enumerate(events) if q==sid))
    plan={'actor':'ASSISTANT','tool':'apply_a','arguments':{'record_id':'X','amount':2},
          'action_quote':'I can modify record X to amount 2.',
          'bindings':[{'path':'/record_id','value':'X','source_id':sid,'quote':'record X'},
                      {'path':'/amount','value':2,'source_id':sid,'quote':'amount 2'}],
          'reply':{'source_ids':uid,'kind':'CONFIRM' if reply else 'NONE',
                   'quotes':[{'source_id':uid[0],'quote':reply}] if reply else []}}
    data={'messages':[{'source_id':sid,'kind':'ACTION_REQUEST','plans':[plan]}]}
    return s,t,data


@pytest.mark.parametrize('reply,kind,want',[('Yes','CONFIRM','TRUE'),('No','REFUSE','FALSE'),
    ('No problem, go ahead','CONFIRM','TRUE'),('Да, подтверждаю. Спасибо!','CONFIRM','TRUE'),
    ('Да, если цена не изменится','CONDITIONAL','UNRESOLVED'),(None,'NONE','FALSE')])
def test_scoped_full_reply_can_be_classified_without_word_dictionary(reply,kind,want):
    s,t,data=fixture(reply);data['messages'][0]['plans'][0]['reply']['kind']=kind
    got=c.admit(data,s,t);assert got['valid']
    result=c.verdict(got,s,t)
    assert result['value']==want and result['code_proof'] is False


def test_hidden_target_amount_cannot_be_copied_backwards():
    s,t,data=fixture(amount=999)
    request=c.packet(s,t)
    assert '999' not in json.dumps(request)
    assert c.verdict(c.admit(data,s,t),s,t)['value']=='UNRESOLVED'


def test_factual_question_has_no_operation_to_confirm():
    s,t,data=fixture('No')
    data['messages'][0].update(kind='FACT_QUESTION',plans=[])
    assert c.verdict(c.admit(data,s,t),s,t)['value']=='UNRESOLVED'


@pytest.mark.parametrize('failure',['number','parent','missing_leaf','future_source','invented_quote','wrong_role'])
def test_unsupported_binding_cannot_resolve(failure):
    s,t,data=fixture();p=data['messages'][0]['plans'][0]
    if failure=='number':p['arguments']['amount']=999;p['bindings'][1]['value']=999
    elif failure=='parent':p['arguments']['record_id']='Y';p['bindings'][0]['value']='Y'
    elif failure=='missing_leaf':p['bindings'].pop()
    elif failure=='future_source':p['bindings'][1]['source_id']='t0'
    elif failure=='invented_quote':p['action_quote']='I already modified X.'
    else:p['reply']['source_ids']=[data['messages'][0]['source_id']]
    assert not c.admit(data,s,t)['valid']


def test_identical_narration_keeps_answered_proposal():
    s,t,data=fixture()
    s=SourceStore({**s.raw,'response':'⟦ASSISTANT⟧\nI will now modify record X to amount 2.\n'+s.raw['response']})
    t=target(s);sid=c.candidates(s,t)[-1][0]
    p=copy.deepcopy(data['messages'][0]['plans'][0]);p.update(action_quote='I will now modify record X to amount 2.')
    for b in p['bindings']:b['source_id']=sid
    p['reply']={'source_ids':[],'kind':'NONE','quotes':[]}
    data['messages'].append({'source_id':sid,'kind':'ACTION_DESCRIPTION','plans':[p]})
    got=c.admit(data,s,t);assert got['valid']
    assert c.verdict(got,s,t)['value']=='TRUE'


def test_identical_native_retry_does_not_reuse_approval():
    s,t,data=fixture()
    s=SourceStore({**s.raw,'response':s.raw['response']+'\n'+s.raw['response']})
    from guardian_truth.source_search.id_contract import native_target_inventory
    t=native_target_inventory(s)[1]
    assert c.verdict(c.admit(data,s,t),s,t)['value']=='UNRESOLVED'


def test_revocation_after_intervening_read_remains_unresolved():
    s,t,data=fixture()
    s=SourceStore({**s.raw,'prompt':s.raw['prompt']+'⟦ASSISTANT⟧\n→ TOOL_CALL inspect_b: {"record_id":"X"}\n'
        '← TOOL_RESPONSE inspect_b: {"record_id":"X"}\n⟦USER⟧\nWait, do not proceed.\n'})
    assert c.verdict(c.admit(data,s,t),s,t)['value']=='UNRESOLVED'


def test_list_parameters_use_typed_leaf_quotes_in_prose():
    s=SourceStore({'prompt':'⟦SYSTEM⟧\n[AVAILABLE TOOLS]\n- apply_a — modify records\n    record_id: string!\n    items: array!\n'
        '⟦ASSISTANT⟧\nModify record X, items I and J. Confirm?\n⟦USER⟧\nYes, both. Thanks!\n',
        'response':'→ TOOL_CALL apply_a: {"record_id":"X","items":["I","J"]}'})
    t=target(s);sid=c.candidates(s,t)[0][0];uid=c.user_block(c.timeline(s,t),next(i for i,(q,_) in enumerate(c.timeline(s,t)) if q==sid))[0]
    args={'record_id':'X','items':['I','J']}
    p={'actor':'ASSISTANT','tool':'apply_a','arguments':args,'action_quote':'Modify record X, items I and J.',
       'bindings':[{'path':path,'value':v,'source_id':sid,'quote':'record X' if path=='/record_id' else 'items I and J'} for path,v in c.leaves(args)],
       'reply':{'source_ids':[uid],'kind':'CONFIRM','quotes':[{'source_id':uid,'quote':'Yes, both.'}]}}
    got=c.admit({'messages':[{'source_id':sid,'kind':'ACTION_REQUEST','plans':[p]}]},s,t)
    assert got['valid'] and c.verdict(got,s,t)['value']=='TRUE'
    changed={**t,'arguments':{**args,'record_id':'Y'}}
    assert c.verdict(got,s,changed)['value']=='UNRESOLVED'


def test_one_model_approval_does_not_become_two_family_agreement():
    s,t,data=fixture();a=c.admit(data,s,t)
    one={'family':'a','admission':a,'verdict':c.verdict(a,s,t)}
    assert c.agreement([one])['value']=='UNRESOLVED'
    assert c.agreement([one,{**one,'family':'b'}])['value']=='TRUE'
    assert not c.agreement([one,{**one,'family':'b'}])['code_proof']


def test_conflicting_duplicate_plan_rejected_before_order_can_pick_yes():
    s,t,data=fixture();p=copy.deepcopy(data['messages'][0]['plans'][0])
    p['reply']['kind']='REFUSE';data['messages'][0]['plans'].append(p)
    assert not c.admit(data,s,t)['valid']


def test_narration_with_added_different_amount_does_not_keep_approval():
    s,t,data=fixture()
    text='I will now modify record X to amount 2; I may also modify it to amount 999.'
    s=SourceStore({**s.raw,'response':'⟦ASSISTANT⟧\n'+text+'\n'+s.raw['response']})
    t=target(s);sid=c.candidates(s,t)[-1][0]
    p=copy.deepcopy(data['messages'][0]['plans'][0]);p.update(action_quote='I will now modify record X to amount 2')
    for b in p['bindings']:b['source_id']=sid
    p['reply']={'source_ids':[],'kind':'NONE','quotes':[]}
    extra=copy.deepcopy(p);extra['arguments']['amount']=999
    extra['action_quote']='I may also modify it to amount 999.'
    extra['bindings'][1].update(value=999,quote='amount 999')
    data['messages'].append({'source_id':sid,'kind':'ACTION_DESCRIPTION','plans':[p,extra]})
    a=c.admit(data,s,t);assert a['valid']
    assert c.verdict(a,s,t)['value']=='UNRESOLVED'


def test_empty_root_arguments_are_valid_partial_plan_but_do_not_match_target():
    s,t,data=fixture();p=data['messages'][0]['plans'][0]
    p.update(arguments={},bindings=[])
    a=c.admit(data,s,t)
    assert a['valid'] and c.verdict(a,s,t)['value']=='UNRESOLVED'


def test_result_payloads_are_omitted_from_model_context():
    s,t,data=fixture()
    s=SourceStore({**s.raw,'prompt':s.raw['prompt']+'⟦ASSISTANT⟧\n→ TOOL_CALL inspect_b: {"record_id":"X"}\n'
        '← TOOL_RESPONSE inspect_b: {"private_payload":"DO_NOT_COPY_RESULT_VALUE"}\n'})
    packet=c.packet(s,t)
    assert 'DO_NOT_COPY_RESULT_VALUE' not in json.dumps(packet)
    assert any(e['kind']=='result' and e['payload_omitted'] for e in packet['prior_events'])
