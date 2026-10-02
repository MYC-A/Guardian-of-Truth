"""Revalidate the already saved single-call direct replies; zero HTTP calls."""
import json
from acceptance import ROOT
from run_compare import write
from guardian_truth.source_search.pipeline import decode_model_object, validate_assessment
from guardian_truth.source_search.store import SourceStore


out = ROOT / 'outputs/searh_23/source_search_20261002/model_preflight_v3'
inputs = {r['id']: r for r in json.loads((out/'frozen.json').read_text(encoding='utf-8'))['inputs']}
records = [json.loads(line) for line in (out/'predictions.jsonl').read_text(encoding='utf-8').splitlines()]
results = []
for record in records:
    if record['mode'] != 'direct':
        continue
    result = {'id':record['case_id'], 'model':record['model'], 'previous_decision':record['decision']}
    model = record['trace'][0]['model']
    try:
        vote = decode_model_object(model['content'])['assessment']
        result['assessment'] = validate_assessment(SourceStore(inputs[record['case_id']]), vote)
        result['decision'] = result['assessment']['decision']
    except (ValueError, TypeError, KeyError) as exc:
        result.update(decision='UNKNOWN', error=str(exc))
    results.append(result)
write(out/'format_replay.json', {'scope':'SAME_SAVED_REPLY_FORMAT_ONLY_NOT_NEW_MODEL_RUN',
    'http_calls':0, 'gold_opened':False, 'records':results})
print(json.dumps([{k:v for k,v in r.items() if k!='assessment'} for r in results]))
