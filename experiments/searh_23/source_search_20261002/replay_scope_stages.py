"""Verify canonical src matches the live-tested batch mechanism, zero HTTP."""
import json
from acceptance import ROOT
from guardian_truth.source_search.store import SourceStore
from guardian_truth.source_search.scope_stages import parse_stores,request
from run_compare import write

OUT=ROOT/'outputs/searh_23/source_search_20261002/move_intent_probe_v1'
protocol=json.loads((OUT/'frozen.json').read_text(encoding='utf-8'))
checked=0
for offset in range(0,32,8):
    rows=protocol['rows'][offset:offset+8]; stores={row['id']:SourceStore(row) for row in rows}
    for stage in ('act','intent'):
        messages,schema=request(stage,stores)
        if schema!=protocol[stage+'_schema'] or messages[0]['content']!=protocol[stage+'_instruction']:
            raise ValueError('canonical schema/prompt differs from tested protocol')
    def ask(stage):
        saved=json.loads((OUT/f'batch_{offset}_{stage}.json').read_text(encoding='utf-8'))
        return lambda _:saved['raw_record']
    result=parse_stores(stores,ask('act'),ask('intent'))
    expected={r['id']:r for r in json.loads((OUT/f'batch_{offset}_validated.json').read_text(encoding='utf-8'))}
    for key,case in result['cases'].items():
        if case.get('move_scope')!=expected[key].get('move_scope'):
            raise ValueError('canonical result differs from original saved frame')
        checked+=1
write(OUT/'canonical_replay.json',{'http_calls':0,'identical_frames':checked,
    'scope':'EXACT_TESTED_PROMPT_SCHEMA_AND_SAVED_REPLY_REPLAY_NOT_NEW_INFERENCE'})
print(json.dumps({'identical_frames':checked,'http_calls':0}))
