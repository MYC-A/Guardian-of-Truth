"""Code-role correction on SAVED parses, zero new inference, no judge replay."""
import json
from acceptance import ROOT
from run_compare import write
from guardian_truth.source_search.move_scope import validate_parse
from guardian_truth.source_search.pipeline import decode_model_object
from guardian_truth.source_search.store import SourceStore

OUT=ROOT/'outputs/searh_23/source_search_20261002/typed_scope_probe_v2'
protocol=json.loads((OUT/'frozen.json').read_text(encoding='utf-8'))
inputs={r['id']:r for r in protocol['rows']}
records=[json.loads(line) for line in (OUT/'predictions.jsonl').read_text(encoding='utf-8').splitlines()]
seen=set(); results=[]
for row in records:
    if row['arm']=='direct' or row['case_id'] in seen: continue
    seen.add(row['case_id']); rec=row['parse_record']
    result={'id':row['case_id'],'original_parse_error':row.get('error')}
    try:
        result['move_scope']=validate_parse(SourceStore(inputs[row['case_id']]),decode_model_object(rec['content']))
    except (ValueError,KeyError,TypeError) as exc: result['validation_error']=str(exc)
    results.append(result)
write(OUT/'speaker_role_replay.json',{'scope':'POSTHOC_MECHANICAL_ROLE_REPLAY_NOT_NEW_MODEL_OR_VERDICT',
    'http_calls':0,'results':results,'original_predictions_unchanged':True})
print(json.dumps([{'id':r['id'],'error':r.get('validation_error'),'issues':r.get('move_scope',{}).get('issues')} for r in results]))
