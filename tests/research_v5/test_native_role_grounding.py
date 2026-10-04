from copy import deepcopy
import json
import pytest
from experiments.research_v5.process_grounding import build
from experiments.research_v5.native_role_grounding import check_role, execute


def event(tool,args,value=None):
    s='⟦ASSISTANT⟧\n→ TOOL_CALL '+tool+': '+json.dumps(args)+'\n'
    if value is not None:s+='← TOOL_RESPONSE '+tool+': '+json.dumps(value)+'\n'
    return s


def fixture(*,later_id='B',later_end='2025-04-01',parallel=False):
    p='⟦SYSTEM⟧\nThe current time is 2025-02-25 12:08:00 EST. Do not update entities with end date in the past.\n[AVAILABLE TOOLS]\n- read — Reads an object by identifier.\n    id: string!\n- update — Updates entity_id.\n    entity_id: string!\n⟦USER⟧\nUpdate entity A.\n'
    if parallel:
        p+=event('read',{'id':'A'})+event('read',{'id':later_id})
        p+='← TOOL_RESPONSE read: '+json.dumps({'entity_id':'A','end':'2025-01-31'})+'\n'
    else:
        p+=event('read',{'id':'A'},{'entity_id':'A','end':'2025-01-31'})
        p+=event('read',{'id':later_id},{'entity_id':later_id,'end':later_end})
    row={'prompt':p,'response':event('update',{'entity_id':'A'})}
    g,f,a,_=build(row);tid=next(iter(g.targets));source=next(s for s,v in g.store.sources.items() if v['kind']=='result')
    F=lambda sid,k:next(i for i,v in f.items() if v['source_id']==sid and v['record_keys']==[k])
    A=next(i for i,v in a.items() if v['declaration_id']==g.declarations['read'] and v['name']=='id')
    rule=dict(target_id=tid,regulated_action='Update past-date entity',policy_ids=['p0'],modality='FORBID',applies='YES',
        fact_field=F(source,'end'),target_identity_field=F(tid,'entity_id'),read_call_argument=A,
        result_identity_field=F(source,'entity_id'),operation='DATE_BEFORE_SYSTEM_DATE',exemption='NO',exception_policy_ids=[],unresolved=[])
    reply=dict(process=dict(coverage='UNRESOLVED',rules=[],open_questions=[],reason='No process query'),
               native_role_rules=[rule],open_questions=[],reason='Date/role query')
    return row,reply,rule


def test_other_entity_receipt_does_not_shadow_and_original_is_preserved():
    row,reply,rule=fixture();original=deepcopy(row)
    out=execute(row,reply,complete=True)
    assert out['decision']=='ERROR' and out['binary']==1
    fact=out['native_roles'][0]['fact']
    assert fact['value']=='TRUE' and len(fact['excluded_unrelated_unique_receipts'])==2
    assert row==original


def test_later_same_entity_does_shadow_old_record():
    row,_,rule=fixture(later_id='A')
    out=check_role(row,rule)
    assert out['value']=='UNKNOWN' and out['cause']=='OBSERVATION_SUPERSEDED_BY_LATER_RESULT'


def test_parallel_receipts_cannot_be_rescued_by_entity_filter():
    row,_,rule=fixture(parallel=True)
    out=check_role(row,rule)
    assert out['value']=='UNKNOWN' and out['cause']=='RESULT_WITHOUT_UNIQUE_VALID_PRIOR_CALL'


def test_permission_does_not_become_prohibition():
    row,reply,_=fixture();reply['native_role_rules'][0]['modality']='PERMIT'
    assert execute(row,reply,complete=True)['decision']=='UNKNOWN'


def test_wrong_argument_alias_and_policy_role_cannot_be_admitted():
    row,reply,rule=fixture();g,f,a,_=build(row)
    rule['read_call_argument']=next(i for i,v in a.items() if v['declaration_id']==g.declarations['update'])
    assert check_role(row,rule)['cause']=='ALIAS_WRONG_READ_DECLARATION'
    reply['native_role_rules'][0]['policy_ids']=[g.declarations['read']]
    with pytest.raises(ValueError,match='POLICY_ROLE_INVALID'):execute(row,reply,complete=True)


def test_unknown_exception_and_semantics_are_not_overruled_by_date():
    row,reply,_=fixture()
    reply['native_role_rules'][0].update(exemption='UNRESOLVED',exception_policy_ids=['p0'])
    assert execute(row,reply,complete=True)['decision']=='UNKNOWN'
    reply['native_role_rules'][0].update(exemption='NO',unresolved=['Entity alias not established'])
    assert execute(row,reply,complete=True)['decision']=='UNKNOWN'
