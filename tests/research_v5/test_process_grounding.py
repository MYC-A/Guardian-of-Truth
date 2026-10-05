"""Contract checks for the research adapter, independent of binary benchmark gold."""
from copy import deepcopy
import json
import pytest
from experiments.research_v5.process_grounding import build, execute, check_prior


def event(tool,args,result=None,role='ASSISTANT'):
    s='⟦'+role+'⟧\n→ TOOL_CALL '+tool+': '+json.dumps(args)+'\n'
    if result is not None:s+='← TOOL_RESPONSE '+tool+': '+json.dumps(result)+'\n'
    return s


def fixture(*,object='X',actor='P',late=False,result=True,tool='inspect',role='ASSISTANT',extra='',target_extra=''):
    policy='Before making the update, obtain a successful check for the same object and actor. No exemption is implied.'
    catalog='[AVAILABLE TOOLS]\n- '+tool+' — Checks authority without updating state.\n    key: string!\n    principal: string!\n- update — Updates the object for an actor.\n    object: string!\n    actor: string!\n'
    check=event(tool,dict(key=object,principal=actor),dict(key=object,principal=actor,approved=result),role)
    target=event('update',dict(object='X',actor='P'))
    row=dict(prompt='⟦SYSTEM⟧\n'+policy+'\n'+catalog+'⟦USER⟧\nPlease update.\n'+('' if late else check)+extra,
             response=target+(check if late else '')+target_extra)
    g,f,a,p=build(row);tid=next(iter(g.targets));sid=next(s for s,x in g.store.sources.items() if x['kind']=='result')
    fid=lambda source,key:next(i for i,v in f.items() if v['source_id']==source and v['record_keys']==[key])
    did=g.declarations[tool]
    aid=lambda key:next(i for i,v in a.items() if v['declaration_id']==did and v['name']==key)
    c=dict(meaning='Same object/actor successful prior check',declaration_id=did,mode='SUCCESSFUL_BOOLEAN_CHECK',
           outcome_field=fid(sid,'approved'),joins=[
               dict(role='object',target_field=fid(tid,'object'),call_argument=aid('key'),result_field=fid(sid,'key')),
               dict(role='actor',target_field=fid(tid,'actor'),call_argument=aid('principal'),result_field=fid(sid,'principal'))],unresolved=[])
    reply=dict(coverage='COMPLETE_OPINION',rules=[dict(target_id=tid,regulated_action='Update object',policy_ids=['p0'],applies='YES',
                prerequisite_any_of=[dict(all_of=[c])],exemption='NO',exception_policy_ids=[],exception_evidence_ids=[],
                grounding_evidence_ids=[sid],unresolved=[])],open_questions=[],reason='Test oracle')
    return row,reply,c


def status(result):return result['relations'][0]['requirement']['status']


@pytest.mark.parametrize('options',[dict(object='Y'),dict(actor='Q'),dict(late=True),dict(result=False)])
def test_missing_success_requires_explicit_process_completeness(options):
    row,reply,_=fixture(**options)
    assert status(execute(row,reply,complete=True))=='VIOLATED'
    assert status(execute(row,reply,complete=False))=='UNKNOWN'


def test_success_is_not_a_whole_move_certificate_and_no_truncation():
    row,reply,_=fixture()
    g,_,_,packet=build(row)
    assert packet['original']=={k:row[k] for k in ('prompt','response')}
    out=execute(row,reply,complete=True)
    assert status(out)=='SATISFIED' and out['decision']=='UNKNOWN' and out['binary']==0
    assert not out['world_state_absence_is_false'] and not out['code_proof']
    g._assert_integrity()


def test_rename_and_alias_roles_are_not_business_tool_rules():
    for tool in ('inspect','opaque_781'):
        row,reply,_=fixture(tool=tool)
        assert status(execute(row,reply,complete=True))=='SATISFIED'


@pytest.mark.parametrize('value',[1,0,'true',None])
def test_truthy_scalars_cannot_certify_success(value):
    row,reply,_=fixture(result=value)
    assert status(execute(row,reply,complete=True))=='UNKNOWN'


def test_user_check_is_not_assistant_process():
    row,reply,_=fixture(role='USER')
    # A user receipt is rejected by the original checker; uncertainty must not
    # turn it into a certified assistant check or a false world fact.
    assert status(execute(row,reply,complete=True))=='UNKNOWN'


def test_ambiguous_parallel_receipts_remain_unknown():
    row,reply,_=fixture()
    row['prompt']=row['prompt'].replace('← TOOL_RESPONSE inspect:', '→ TOOL_CALL inspect: {"key":"X","principal":"P"}\n← TOOL_RESPONSE inspect:')
    # Candidate IDs after this insertion must be authored against the new source.
    g,f,a,_=build(row)
    sid=next(s for s,x in g.store.sources.items() if x['kind']=='result')
    for j,k in zip(reply['rules'][0]['prerequisite_any_of'][0]['all_of'][0]['joins'],('key','principal')):
        j['result_field']=next(i for i,v in f.items() if v['source_id']==sid and v['record_keys']==[k])
    reply['rules'][0]['prerequisite_any_of'][0]['all_of'][0]['outcome_field']=next(i for i,v in f.items() if v['source_id']==sid and v['record_keys']==['approved'])
    tid=next(iter(g.targets));reply['rules'][0]['target_id']=tid
    for j,k in zip(reply['rules'][0]['prerequisite_any_of'][0]['all_of'][0]['joins'],('object','actor')):
        j['target_field']=next(i for i,v in f.items() if v['source_id']==tid and v['record_keys']==[k])
    assert status(execute(row,reply,complete=True))=='UNKNOWN'


def test_exception_scope_and_unresolved_applicability():
    row,reply,_=fixture(late=True)
    reply['rules'][0].update(exemption='YES',exception_policy_ids=['p0'])
    assert status(execute(row,reply,complete=True))=='NOT_TRIGGERED'
    reply['rules'][0].update(exemption='UNRESOLVED')
    assert status(execute(row,reply,complete=True))=='UNKNOWN'
    reply['rules'][0].update(exemption='NO',applies='UNRESOLVED')
    assert status(execute(row,reply,complete=True))=='UNKNOWN'


def test_and_or_composition_does_not_flatten_alternatives():
    row,reply,c=fixture()
    false=deepcopy(c);false['mode']='ATTEMPT';false['outcome_field']=None
    g,_,_,_=build(row);false['declaration_id']=g.declarations['update'];false['joins']=[]
    reply['rules'][0]['prerequisite_any_of']=[dict(all_of=[c,false])]
    assert status(execute(row,reply,complete=True))=='VIOLATED'
    reply['rules'][0]['prerequisite_any_of']=[dict(all_of=[c]),dict(all_of=[false])]
    assert status(execute(row,reply,complete=True))=='SATISFIED'


def test_source_roles_and_integrity_are_not_disabled():
    row,reply,c=fixture();g,f,a,_=build(row)
    reply['rules'][0]['policy_ids']=[g.declarations['inspect']]
    with pytest.raises(ValueError,match='POLICY_ROLE_INVALID'):execute(row,reply,complete=True)
    with pytest.raises(TypeError):g.store.raw['prompt']+='tamper'  # integrated_v1: backing is read-only
    dict.__setitem__(g.store.raw,'prompt',g.store.raw['prompt']+'tamper')  # forced bypass: downstream check must still fire
    with pytest.raises(ValueError,match='SOURCE_OR_NATIVE_PARSE_CHANGED'):
        check_prior(g,f,a,next(iter(g.targets)),c,complete=True)


def test_second_current_call_can_be_regulated():
    row,reply,c=fixture(late=True)
    # Current sequence: first update, later inspection, second update. The second
    # action has a qualifying prior check; the first does not. Whole move is 1.
    row['response']+=event('update',dict(object='X',actor='P'))
    g,f,a,_=build(row);targets=[s for s,v in g.targets.items() if v['tool']=='update']
    second=deepcopy(reply['rules'][0]);second['target_id']=targets[-1]
    for j,k in zip(second['prerequisite_any_of'][0]['all_of'][0]['joins'],('object','actor')):
        j['target_field']=next(i for i,v in f.items() if v['source_id']==targets[-1] and v['record_keys']==[k])
    reply['rules'].append(second)
    out=execute(row,reply,complete=True)
    assert [r['requirement']['status'] for r in out['relations']]==['VIOLATED','SATISFIED']
    assert out['decision']=='ERROR'
