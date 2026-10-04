"""Post-hoc, gold-reading audit of the frozen V5 diagnostic. No inference.

Separate from the sealed inference source set: never repairs model replies or
changes predictions. Includes admission failures in executed-pair binary scores.
"""
from collections import Counter
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'experiments/research_v5/diagnostics'))
from binary_audit import metrics
from experiments.research_v5.process_grounding import build
from experiments.research_v5.native_role_grounding import GroundedReply
import pandas as pd


def main(out):
    records=json.loads((out/'predictions.json').read_text(encoding='utf-8'))
    ledger=json.loads((out/'ledger.json').read_text(encoding='utf-8'))
    protocol=json.loads((out/'protocol.json').read_text(encoding='utf-8'))
    original=pd.read_parquet(ROOT/'valid.parquet')
    gold=dict(zip(original.id,original.label.map(int)))
    rows={r.id:r.to_dict() for _,r in original.iterrows()}
    lookup={(r['id'],r['arm']):r for r in records}
    selected=sorted({r['id'] for r in records})
    executed=[i for i in selected if all(lookup[i,a]['request_sha256'] in ledger and
        ledger[lookup[i,a]['request_sha256']]['status']=='OK' for a in ('D0','P3'))]
    wire=[]
    for r in records:
        if r['arm']!='P3' or r['reply'] is None:continue
        graph,fields,args,_=build(rows[r['id']])
        GroundedReply.model_validate(r['reply'])
        errors=[];count=Counter()
        def walk(v,path='reply'):
            if isinstance(v,dict):
                for key,value in v.items():
                    choices=None
                    if key=='target_id':choices=graph.targets
                    if key in ('policy_ids','exception_policy_ids'):choices=graph.units
                    if key=='declaration_id':choices=set(graph.declarations.values())
                    if key in ('call_argument','read_call_argument'):choices=args
                    if key in ('target_field','result_field','fact_field','outcome_field','target_identity_field','result_identity_field'):choices=fields
                    if choices is not None:
                        for item in (value if isinstance(value,list) else [value]):
                            if item is None:continue
                            count['references']+=1
                            if item not in choices:errors.append(dict(path=path+'.'+key,value=item,cause='OUTSIDE_CODE_OWNED_CANDIDATES'));count['invalid']+=1
                    walk(value,path+'.'+key)
            elif isinstance(v,list):
                for n,x in enumerate(v):walk(x,path+'.'+str(n))
        walk(r['reply'])
        wire.append(dict(id=r['id'],strict_shape_valid=True,runtime_failure=r['failure'],
                         actual_native_targets=list(graph.targets),reference_counts=count,reference_errors=errors))
    native=next(i for i in executed if i.startswith('telecom__'))
    negative=next(i for i in executed if i.startswith('banking_knowledge__'))
    graph,fields,args,_=build(rows[native])
    selected_role=lookup[native,'P3']['reply']['native_role_rules'][0]
    fields_selected={k:fields.get(selected_role[k]) for k in ('fact_field','target_identity_field','result_identity_field')}
    alias=args.get(selected_role['read_call_argument'])
    scores={a:metrics({i:gold[i] for i in executed},{i:lookup[i,a]['result']['binary'] for i in executed}) for a in ('D0','P3')}
    for a in scores:
        scores[a]['decisions']=Counter(lookup[i,a]['result']['decision'] for i in executed)
        scores[a]['failures']=Counter(lookup[i,a]['failure'] for i in executed if lookup[i,a]['failure'])
    report=dict(phase='POST_HOC_SOURCE_AND_CAUSE_AUDIT_NOT_REPLY_REPAIR',new_http=0,
        protocol_sha256=protocol['protocol_sha256'],common_transport_executed_ids=executed,
        executed_binary_scores_including_admission_failures=scores,
        fully_admitted_pairs=0,fully_admitted_comparative_F1=None,
        syntax_valid_P3_replies=len(wire),P3_code_candidate_admitted=0,wire_audit=wire,
        confirmed_automatically_correct_applicable_native_norms=0,
        oracle_native_norm_recall=dict(required=1,recovered=0,norm='Do not lift suspension when the same line contract end date is past; payment does not waive it.'),
        semantic_audit=[dict(id=native,official_gold=1,
            direct_binary_correct=True,direct_positive_cause_correct=False,
            direct_problem='D0 accuses historical make_payment h27 and user-side h30, calls the CURRENT resume_line correct, and misses the actual expired-contract prohibition.',
            actor_evidence={s:{k:graph.refs[s][k] for k in ('document','kind','role','tool')} for s in ('h27','h30','t0')},
            P3_problem='Business ID L1002 is used as target_id instead of t0; status/time fields are not native boolean outcomes. The native rule uses PERMIT and denies date restrictions despite the explicit prohibition.',
            selected_native_fields=fields_selected,selected_read_alias=alias,
            role_problem='Fact is suspension_start_date, supposed target identity is historical phone_number, supposed result identity is the current call, and alias belongs to resume_line rather than the read declaration.'),
            dict(id=negative,official_gold=0,direct_binary_correct=True,direct_scope_correct=True,
                 P3_problem='No current native target exists. P3 selects user source h2 as an opening action, attaches checking-account requirements to a verification request, and invents field IDs. UNKNOWN→0 agrees with gold without semantic success.')],
        cause_valid_direct_positives=dict(correct=0,binary_true_positives=1,human_posthoc_opinion=True),
        budget_stop_ids=[i for i in selected if i not in executed],
        architecture_improvement_claim=False,automatic_full_valid46_metric_available=False,
        conclusion='Grammar-valid JSON and valid policy ID lists coexist with wrong action scope, participant roles and policy meaning. Current P3 has no measured advantage; D0 label accuracy alone hides the wrong positive cause.')
    (out/'posthoc_failure_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(dict(executed_pairs=len(executed),syntax_valid=len(wire),candidate_admitted=0,
                         executed_binary_scores=scores,correct_direct_positive_causes=0),ensure_ascii=False,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);main(p.parse_args().out)
