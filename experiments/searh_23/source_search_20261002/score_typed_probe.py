"""Separate post-run author diagnostic. Refuse partial or duplicate matrices."""
import json
from collections import Counter
from acceptance import ROOT
from run_compare import write

OUT=ROOT/'outputs/searh_23/source_search_20261002/typed_scope_probe_v2'
protocol=json.loads((OUT/'frozen.json').read_text(encoding='utf-8'))
records=[json.loads(line) for line in (OUT/'predictions.jsonl').read_text(encoding='utf-8').splitlines()]
expected={(r['id'],a) for r in protocol['rows'] for a in protocol['arms']}
keys={(r['case_id'],r['arm']) for r in records}
if len(keys)!=len(records) or keys!=expected:
    raise ValueError('require a complete unique 18-record matrix before scoring')
review=ROOT/'outputs/searh_23/source_search_20261002/counterevidence_bank_v2/short_author_review.jsonl'
gold={r['id']:r for line in review.read_text(encoding='utf-8').splitlines() if (r:=json.loads(line))}
summary,details={},[]
for row in records:
    label=gold[row['case_id']]['author_label']; decision=row['decision']
    bucket=('UNKNOWN+' if label else 'UNKNOWN-') if decision=='UNKNOWN' else (
        'TP' if label and decision=='ERROR' else 'FP' if decision=='ERROR' else 'FN' if label else 'TN')
    counts=summary.setdefault(row['arm'],{'buckets':Counter(),'stops':Counter(),
        'actual_api_attempts':0,'known_provider_tokens':0,'unknown_usage_bounds':0})
    counts['buckets'][bucket]+=1; counts['stops'][row.get('stop_reason','unknown')]+=1
    before,after=row['budget_before'],row['budget_after']
    counts['actual_api_attempts']+=after['actual_api_attempts']-before['actual_api_attempts']
    counts['known_provider_tokens']+=after['known_provider_tokens']-before['known_provider_tokens']
    counts['unknown_usage_bounds']+=after['unknown_usage_upper_bounds']-before['unknown_usage_upper_bounds']
    frame=row.get('move_scope',{})
    details.append({'id':row['case_id'],'family':gold[row['case_id']]['family'],'arm':row['arm'],
        'author_label':label,'decision':decision,'bucket':bucket,'stop_reason':row.get('stop_reason'),
        'scope_issues':frame.get('issues'),'intent':frame.get('intent'),
        'acts':[(a['act'],a['modality'],a['performer']) for a in frame.get('acts',[])],
        'parse_error':row.get('error'),'validation_errors':[t.get('validation_error') for t in row.get('trace',[]) if t.get('validation_error')],
        'assessment':row.get('assessment'),'reviewed_assessment':row.get('reviewed_assessment'),
        'graph_roots':row.get('graph_view',{}).get('roots'),
        'graph_truncations':[g.get('was_truncated') for g in row.get('graph_view',{}).get('traversals',[])]})
result={'scope':'AUTHOR_SHORT_ABLATION_NOT_INDEPENDENT_TRANSFER','human_review_status':'PENDING',
        'records':len(records),'summary':summary,'details':details,
        'source_provenance_is_not_entailment':True,'navigation_is_code_selected':True}
write(OUT/'score.json',result)
print(json.dumps(summary))
