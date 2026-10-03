import copy
import pytest
from test_policy_table_v11 import store,target
from guardian_truth.policy_table_v11.semantic_consent import admit,verdict,agreement
from guardian_truth.policy_table_v11.witness import timeline


def fixture(reply='Yes'):
    s=store('⟦ASSISTANT⟧\nI can modify record X to amount 2. Do you confirm?\n'+
            ('⟦USER⟧\n'+reply+'\n' if reply is not None else ''))
    t=target(s)
    sid=next(sid for sid,e in timeline(s,t) if e.role=='assistant' and e.kind=='text')
    data={'descriptions':[{'source_id':sid,'kind':'ACTION_REQUEST','reason':'Explicit action proposal and approval question.',
        'frame':{'actor':'ASSISTANT','tool':'apply_a','arguments':{'record_id':'X','amount':2},
            'action_quote':'I can modify record X to amount 2. Do you confirm?',
            'argument_sources':{'record_id':[{'source_id':sid,'quote':'record X'}],
                                'amount':[{'source_id':sid,'quote':'amount 2'}]}}}]}
    return s,t,data


@pytest.mark.parametrize('reply,want',[('Yes','TRUE'),('Да','TRUE'),('No','FALSE'),(None,'FALSE'),
    ('Yes, I refuse to approve','UNRESOLVED'),('«No»','UNRESOLVED'),('Yes, if permitted','UNRESOLVED')])
def test_code_checks_full_reply_after_model_action_binding(reply,want):
    s,t,data=fixture(reply)
    checked=admit(data,s,t)
    assert checked['valid']
    got=verdict(checked,s,t)
    assert got['value']==want and not got['code_proof']


@pytest.mark.parametrize('edit', ['changed_amount','missing_argument','future_source','invalid_quote','wrong_tool','duplicate_description'])
def test_rejects_unbacked_or_incomplete_binding(edit):
    s,t,data=fixture()
    f=data['descriptions'][0]['frame']
    if edit=='changed_amount':f['arguments']['amount']=999
    elif edit=='missing_argument':f['arguments'].pop('amount');f['argument_sources'].pop('amount')
    elif edit=='future_source':f['argument_sources']['amount'][0]['source_id']='t0'
    elif edit=='invalid_quote':f['action_quote']='I modified X already.'
    elif edit=='wrong_tool':f['tool']='inspect_b'
    else:data['descriptions']*=2
    checked=admit(data,s,t)
    assert not checked['valid'] or verdict(checked,s,t)['value']=='UNRESOLVED'


def test_approval_of_different_proposed_arguments_never_binds_current_target():
    s,t,data=fixture()
    t={**t,'arguments':{'record_id':'X','amount':999}}
    checked=admit(data,s,t)
    assert checked['valid'] and verdict(checked,s,t)['value']=='UNRESOLVED'


def test_two_equal_verdicts_without_equal_semantics_are_not_agreement():
    s,t,data=fixture();a=admit(data,s,t)
    changed=copy.deepcopy(data);changed['descriptions'][0]['kind']='ACTION_DESCRIPTION'
    b=admit(changed,s,t)
    records=[{'family':'one','admission':a,'verdict':verdict(a,s,t)},
             {'family':'two','admission':b,'verdict':verdict(b,s,t)}]
    assert not agreement(records)['agrees']
    records[1]['admission']=a
    assert agreement(records)['agrees']
    assert not agreement(records)['code_proof']


@pytest.mark.parametrize('quote',['1e-2','part-2','X.2','amount -2','version-2','amount 02'])
def test_no_numeric_fragment_provenance(quote):
    from guardian_truth.policy_table_v11.semantic_consent import value_supported
    assert not value_supported(2,[quote])


@pytest.mark.parametrize('quote',['amount 2.00','amount 2.','amount 2e0','amount +2'])
def test_complete_typed_numeric_provenance(quote):
    from guardian_truth.policy_table_v11.semantic_consent import value_supported
    assert value_supported(2,[quote])


def test_later_nonaction_text_does_not_make_prior_proposal_unanswered_violation():
    s,t,data=fixture(None)
    from guardian_truth.source_search.store import SourceStore
    from guardian_truth.policy_table_v11.witness import timeline
    s=SourceStore({**s.raw,'prompt':s.raw['prompt']+'⟦ASSISTANT⟧\nActually I will inspect X instead.\n'})
    sid=next(sid for sid,e in reversed(timeline(s,t)) if e.kind=='text' and e.role=='assistant')
    data['descriptions'].append({'source_id':sid,'kind':'OTHER','reason':'Superseded write proposal.','frame':None})
    checked=admit(data,s,t)
    assert checked['valid'] and verdict(checked,s,t)['value']=='UNRESOLVED'
