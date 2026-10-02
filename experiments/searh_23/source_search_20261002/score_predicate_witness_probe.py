"""Open frozen authored expectations only after the finite pilot completes."""
import json
from collections import Counter,defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'outputs/searh_23/source_search_20261002/predicate_witness_probe_v1'


def main():
    status=json.loads((OUT/'status.json').read_text(encoding='utf-8'))
    if status['state']!='COMPLETE':raise ValueError('Do not open gold before completion.')
    rows=[json.loads(line) for line in (OUT/'predictions.jsonl').read_text(encoding='utf-8').splitlines()]
    gold={r['id']:r for r in json.loads((OUT/'author_expectations.json').read_text(encoding='utf-8'))}
    groups=defaultdict(Counter); cases=[]
    for r in rows:
        expected=gold[r['id']]['expected_error_condition']; actual=r['predicate_value']
        outcome='UNKNOWN' if actual is None else 'MATCH' if actual is expected else 'WRONG'
        for subset in ('ALL',gold[r['id']]['subset']):
            counts=groups[(r['provider'],subset)]
            counts[outcome]+=1;counts['records']+=1
            if expected:counts['positive_'+outcome]+=1
            else:counts['negative_'+outcome]+=1
        cases.append({'id':r['id'],'provider':r['provider'],'subset':gold[r['id']]['subset'],
            'expected_error_condition':expected,'predicate_value':actual,'outcome':outcome,
            'status':r['status'],'error':r.get('error'),'formula':r.get('formula'),
            'trace_issues':[n for n in r.get('trace',[]) if n.get('issue')],
            'observed_sources_read':r.get('observed_sources_read',[]),
            'provider_tokens':r['record'].get('usage',{}).get('total_tokens')})
    before=rows[0]['budget_before'];after=rows[-1]['budget_after']
    result={'scope':'AUTHOR_LABEL_DIAGNOSTIC_OF_MODEL_FORMULAS_NOT_CERTIFIED_POLICY_OR_GLOBAL_NO_ERROR',
        'human_review':'PENDING', 'same_model_repair_after_first_response':False,
        'distinct_cases':len(gold),'records':len(rows),
        'models':{provider:{subset:dict(counts) for (p,subset),counts in groups.items() if p==provider}
                  for provider in {r['provider'] for r in rows}},
        'new_http_attempts':after['actual_api_attempts']-before['actual_api_attempts'],
        'known_provider_tokens':after['known_provider_tokens']-before['known_provider_tokens'],
        'final_budget':after,'cases':cases}
    (OUT/'score.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('cases','final_budget')},ensure_ascii=False))


if __name__=='__main__':main()
