"""Read-only investigation mechanism audit; never reads gold or makes API calls."""
import argparse
from collections import Counter
import json
from pathlib import Path
from acceptance import ROOT
from guardian_truth.source_search.pipeline import decode_model_object


def audit(records):
    totals={};cases=[]
    for arm in ('direct','search'):
        operations=Counter();finishes=Counter();errors=Counter();decisions=Counter()
        empty_checks=Counter();steps=Counter();unread=0;final_answers=0
        for row in records:
            if row['mode']!=arm:continue
            trace=row.get('module_trace',[]);decisions[row['decision']]+=1;steps[len(trace)]+=1
            votes=[];actions=[]
            for event in trace:
                model=event.get('model',{});finishes[str(model.get('finish_reason'))]+=1
                if event.get('validation_error'):errors[event['validation_error']]+=1
                action=event.get('action',{}).get('action',{})
                if action:
                    op=action['op'];operations[op]+=1
                    if op=='traverse':operations['traverse/'+action.get('args',{}).get('strategy','BFS')]+=1
                    actions.append({'step':event['step'],'phase':event['phase'],**action,
                        'was_truncated':event.get('result',{}).get('was_truncated',False)})
                try:parsed=decode_model_object(model.get('content',''))
                except (ValueError,TypeError):continue
                if isinstance(parsed,dict) and isinstance(parsed.get('assessment'),dict):
                    vote=parsed['assessment'];votes.append(vote)
                    if event.get('phase')=='FINAL':final_answers+=1
                    checks=vote.get('checks',{})
                    if isinstance(checks,dict):
                        for q,c in checks.items():
                            if isinstance(c,dict) and c.get('status')!='OPEN' and not c.get('evidence_ids'):
                                empty_checks[q]+=1
            coverage=row.get('coverage',{})
            unread+=coverage.get('stop_reason')=='unread_material_query_remainder'
            cases.append({'id':row['case_id'],'arm':arm,'decision':row['decision'],
                'structural':coverage.get('structural')=='confirmed_hit',
                'stop_reason':coverage.get('stop_reason','structural_confirmed_hit'),
                'steps':len(trace),'actions':actions,'last_raw_vote':votes[-1] if votes else None,
                'validation_errors':[e['validation_error'] for e in trace if 'validation_error' in e],
                'assessment_validation':next((e['assessment_validation'] for e in reversed(trace)
                    if 'assessment_validation' in e),None),
                'source_archive':row.get('source_archive'),
                'http_attempts':row['cost_after']['actual_api_attempts']-row['cost_before']['actual_api_attempts'],
                'known_tokens':row['cost_after']['known_provider_tokens']-row['cost_before']['known_provider_tokens']})
        totals[arm]={'decisions':dict(decisions),'operations':dict(operations),
            'finish_reasons':dict(finishes),'validation_errors':dict(errors),
            'empty_evidence_closed_checks':dict(empty_checks),'step_distribution':dict(steps),
            'unread_material_cases':unread,'final_assessment_objects':final_answers}
    return {'scope':'MECHANISM_AND_FORMAT_ONLY_NO_GOLD_NO_SEMANTIC_CERTIFICATION',
            'records':len(records),'totals':totals,'cases':cases}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('directory',type=Path)
    args=parser.parse_args()
    records=[json.loads(line) for line in (args.directory/'predictions.jsonl').read_text(encoding='utf-8').splitlines()]
    result=audit(records)
    (args.directory/'mechanism_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result['totals']))


if __name__=='__main__':main()
