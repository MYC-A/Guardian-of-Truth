"""Post-run author-label diagnostic, kept out of inference code."""
import json
from collections import Counter
from acceptance import ROOT
from run_compare import write

OUT=ROOT/'outputs/searh_23/source_search_20261002/model_preflight_v3'
rows=[json.loads(line) for line in (OUT/'predictions.jsonl').read_text(encoding='utf-8').splitlines()]
frozen=json.loads((OUT/'frozen.json').read_text(encoding='utf-8'))
expected={(r['id'],m['provider'],a) for r in frozen['inputs'] for m in frozen['models'] for a in frozen['arms']}
keys={(r['case_id'],r['provider'],r['mode']) for r in rows}
if len(keys)!=len(rows) or keys!=expected:
    raise RuntimeError('require complete 24 records before author-label diagnostic')
review=ROOT/'outputs/searh_23/source_search_20261002/transfer_v1/author_gold_review_queue.jsonl'
gold={r['id']:r for line in review.read_text(encoding='utf-8').splitlines() if (r:=json.loads(line))}
summary={}
details=[]
for row in rows:
    key=row['model']+'/'+row['mode']
    counts=summary.setdefault(key,{'buckets':Counter(),'stops':Counter(),'operations':Counter(),
        'actual_api_attempts':0,'known_provider_tokens':0,'unknown_usage_bounds':0})
    label=gold[row['case_id']]['label']; decision=row['decision']
    bucket=('UNKNOWN+' if label else 'UNKNOWN-') if decision=='UNKNOWN' else (
        'TP' if label and decision=='ERROR' else 'FP' if decision=='ERROR' else 'FN' if label else 'TN')
    counts['buckets'][bucket]+=1; counts['stops'][row['stop_reason']]+=1
    before,after=row['budget_before'],row['budget_after']
    counts['actual_api_attempts']+=after['actual_api_attempts']-before['actual_api_attempts']
    counts['known_provider_tokens']+=after['known_provider_tokens']-before['known_provider_tokens']
    counts['unknown_usage_bounds']+=after['unknown_usage_upper_bounds']-before['unknown_usage_upper_bounds']
    errors=[]; computations=[]; phase_counts=Counter()
    for trace in row['trace']:
        phase_counts[trace['phase']]+=1
        if trace.get('validation_error'): errors.append(trace['validation_error'])
        action=trace.get('action',{}).get('action')
        if action:
            counts['operations'][action['op']]+=1
            if action['op']=='traverse':
                counts['operations']['traverse/'+action['args'].get('strategy','BFS')]+=1
            if action['op']=='calculate': computations.append(trace['result'])
    details.append({'id':row['case_id'],'family':gold[row['case_id']]['group'],'author_label':label,
        'model':row['model'],'arm':row['mode'],'decision':decision,'bucket':bucket,
        'stop':row['stop_reason'],'phases':dict(phase_counts),'validation_errors':errors,
        'computations':computations,'assessment':row['assessment']})
result={'scope':'AUTHOR_LABEL_DIAGNOSTIC_NOT_INDEPENDENT_TRANSFER','human_review_status':'PENDING',
        'records':len(rows),'summary':summary,'details':details}
write(OUT/'score.json',result)
print(json.dumps(summary))
