"""Strict authored component metrics; only after all 32 cases exist."""
import json
from collections import Counter
from acceptance import ROOT
from run_compare import write

OUT=ROOT/'outputs/searh_23/source_search_20261002/move_intent_probe_v1'
protocol=json.loads((OUT/'frozen.json').read_text(encoding='utf-8'))
records=[r for offset in range(0,32,8) for r in json.loads((OUT/f'batch_{offset}_validated.json').read_text(encoding='utf-8'))]
expected={r['id'] for r in protocol['rows']}
if len({r['id'] for r in records})!=32 or {r['id'] for r in records}!=expected:
    raise ValueError('require all 32 cases, no duplicates')
review=ROOT/'outputs/searh_23/source_search_20261002/move_intent_bank_v1/author_review.jsonl'
gold={r['id']:r for line in review.read_text(encoding='utf-8').splitlines() if (r:=json.loads(line))}
summary={'cases':32,'valid_frames':0,'complete_source_coverage':0,'intent_exact':0,
         'act_kind_exact':0,'act_modality_performer_exact':0,'full_component_exact':0}
details=[]
for row in records:
    label=gold[row['id']]; frame=row.get('move_scope'); flags={}
    if frame:
        actual=[(a['act'],a['modality'],a['performer']) for a in frame['acts']]
        expected_acts=[tuple(a) for a in label['acts']]
        flags={'valid_frames':True,'complete_source_coverage':not frame['issues'],
            'intent_exact':frame['intent']['status']==label['intent'],
            'act_kind_exact':Counter(a[0] for a in actual)==Counter(a[0] for a in expected_acts),
            'act_modality_performer_exact':Counter(actual)==Counter(expected_acts)}
        flags['full_component_exact']=all(flags.values())
        for key,value in flags.items(): summary[key]+=int(value)
        detail={**row,'language':label['language'],'expected_acts':expected_acts,'expected_intent':label['intent'],
                'actual_acts':actual,'metrics':flags}
    else: detail={**row,'language':label['language'],'metrics':flags}
    details.append(detail)
cost={'actual_api_attempts':0,'known_provider_tokens':0,'unknown_usage_bounds':0}
for offset in range(0,32,8):
    for stage in ('act','intent'):
        rec=json.loads((OUT/f'batch_{offset}_{stage}.json').read_text(encoding='utf-8'))
        before,after=rec['budget_before'],rec['budget_after']
        cost['actual_api_attempts']+=after['actual_api_attempts']-before['actual_api_attempts']
        cost['known_provider_tokens']+=after['known_provider_tokens']-before['known_provider_tokens']
        cost['unknown_usage_bounds']+=after['unknown_usage_upper_bounds']-before['unknown_usage_upper_bounds']
write(OUT/'score.json',{'scope':'STRICT_AUTHOR_COMPONENT_DIAGNOSTIC_NOT_VERDICT_TRANSFER',
    'human_review_status':'PENDING','summary':summary,'cost':cost,'details':details})
print(json.dumps({'summary':summary,'cost':cost}))
