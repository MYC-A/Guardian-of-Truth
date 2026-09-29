"""Frozen end-to-end oracle-contract controls; no LLM and no automatic IR claim."""
from __future__ import annotations
from dataclasses import replace
from pathlib import Path
import json
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parents[2]/'src'))
from guardian_truth.integration.runtime import RuntimeProofLayer, ReviewedRule
from guardian_truth.step2.trusted import ReviewedBinding, producer_scope
from guardian_truth.step2.types import EffectStrength, Authority
from guardian_truth.step2.verifier import CallEvent, ResultEvent, TrajectoryCase, CandidateFact


POLICY='An operation may execute only if approval for the same item and amount is currently true.'
TOOLS=({'name':'read','description':'Reads approval for the item and amount.',
        'fields':{'item_id':'string','amount':'number'}},
       {'name':'execute','description':'Executes the operation on the item for the amount.',
        'fields':{'item_id':'string','amount':'number'}})


def scenario(row):
    changes=row['changes']
    calls=[CallEvent(0,'prior','read',{'item_id':'E-7','amount':changes.get('evidence_amount',50)})]
    payload={'item_id':changes.get('result_entity','E-7'),'approved':changes.get('approved',True)}
    if changes.get('no_echo'): payload.pop('item_id')
    results=[ResultEvent(changes.get('result_index',1),'prior',
                         'execute' if changes.get('other_result_tool') else 'read',payload)]
    target_index=2
    if changes.get('revoked') or changes.get('renewed'):
        if changes.get('renewed'): results[0]=replace(results[0],payload={**payload,'approved':False})
        calls.append(CallEvent(2,'update','read',{'item_id':'E-7','amount':50}))
        results.append(ResultEvent(3,'update','read',{'item_id':'E-7','approved':bool(changes.get('renewed'))}))
        target_index=4
    if changes.get('late_approval'):
        results[0]=replace(results[0],payload={**payload,'approved':False})
        calls.append(CallEvent(3,'later','read',{'item_id':'E-7','amount':50}))
        results.append(ResultEvent(4,'later','read',{'item_id':'E-7','approved':True}))
    if changes.get('foreign_amount_update'):
        calls.append(CallEvent(2,'foreign','read',{'item_id':'E-7','amount':70}))
        results.append(ResultEvent(3,'foreign','read',{'item_id':'E-7','approved':False}))
        target_index=4
    if changes.get('unscoped_update'):
        calls.append(CallEvent(2,'unscoped','read',{'item_id':'E-7'}))
        results.append(ResultEvent(3,'unscoped','read',{'item_id':'E-7','approved':False}))
        target_index=4
    target=CallEvent(target_index,'target','read' if changes.get('target_is_check') else 'execute',
                      {'item_id':'E-7','amount':50})
    calls.append(target)
    case=TrajectoryCase(row['id'],'runtime control','author',TOOLS,tuple(calls),tuple(results))
    binding=ReviewedBinding(producer_scope(case,'read'),'item.approved','item','item_id','$.item_id',
                             '$.approved',EffectStrength.OBSERVED,Authority.READ_OBSERVATION,
                             ('true','false'),'ENV_TESTED','frozen synthetic read contract')
    rule=ReviewedRule(0,len(POLICY),POLICY,producer_scope(case,'execute'),'item_id','item',
                      'item.approved','true',EffectStrength.OBSERVED,(('amount','amount'),),
                      'ENV_TESTED','frozen synthetic necessary-condition rule')
    if changes.get('rename'):
        mapping={'read':'x17','execute':'x42'}
        case=replace(case,tools=tuple({**t,'name':mapping[t['name']]} for t in case.tools),
                      calls=tuple(replace(c,tool=mapping[c.tool]) for c in case.calls),
                      results=tuple(replace(r,tool=mapping[r.tool]) for r in case.results))
        target=next(c for c in case.calls if c.call_id=='target')
    proposals={}
    for c in case.calls:
        if c.call_id=='target': continue
        r=next(r for r in case.results if r.call_id==c.call_id)
        proposals[c.call_id]=(CandidateFact(changes.get('proposal_predicate','item.approved'),
            'item','item_id','E-7',json.dumps(r.payload['approved']),'$.approved',
            EffectStrength(changes.get('proposal_strength','OBSERVED')),
            is_observation=True,contract_bound=True),)
    layer=RuntimeProofLayer(POLICY,case,proposals,() if changes.get('no_binding') else (binding,))
    answer=layer.check_only_if(rule,target)
    return {**row,'answer':answer,'passed':answer['status']==row['expected'],
            'assessments':[a.as_dict() for a in layer.assessments]}


def run():
    rows=json.loads((HERE/'frozen/runtime_controls.json').read_text(encoding='utf-8'))
    extra=HERE/'frozen/runtime_scope_extra.json'
    if extra.exists(): rows+=json.loads(extra.read_text(encoding='utf-8'))
    results=[scenario(r) for r in rows]
    out=HERE/'outputs'; out.mkdir(exist_ok=True)
    data={'scope':'oracle reviewed contracts and rules; automated NL mapping not measured',
          'passed':sum(r['passed'] for r in results),'total':len(results),'per_case':results}
    (out/'runtime_control_results.json').write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(data['passed'],'/',data['total'],'reviewed-contract controls')
    for r in results:
        if not r['passed']: print('FAIL',r['id'],r['expected'],r['answer']['status'])
    if data['passed']!=data['total']: raise SystemExit(1)


if __name__=='__main__': run()
