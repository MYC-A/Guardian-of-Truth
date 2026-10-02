"""Diagnostic only: bypass the gap gate on saved formulas, never repair them.

Original predictions/score are immutable. This does not promote interpretations
or count the counterfactual as a successful live prediction. Zero HTTP calls.
"""
import json
from collections import Counter,defaultdict
from acceptance import ROOT
from guardian_truth.source_search.store import SourceStore
from predicate_witness import evaluate

OUT=ROOT/'outputs/searh_23/source_search_20261002/predicate_witness_probe_v1'


if __name__=='__main__':
    frozen=json.loads((OUT/'frozen.json').read_text(encoding='utf-8'))
    rows={r['id']:r for r in frozen['rows']}; counts=defaultdict(Counter); results=[]
    for line in (OUT/'predictions.jsonl').read_text(encoding='utf-8').splitlines():
        rec=json.loads(line)
        try:
            formula=json.loads(rec['record']['content'])
            original_gaps=formula.get('gaps'); formula['gaps']=[]
            value=evaluate(SourceStore(rows[rec['id']]),formula)
            result={'predicate_value':value['predicate_value'],'status':value['status'],
                    'trace_issues':[n for n in value.get('trace',[]) if n.get('issue')],
                    'original_gaps':original_gaps}
        except (ValueError,TypeError,KeyError) as exc:
            result={'predicate_value':None,'status':'INVALID','error':str(exc)}
        result.update(id=rec['id'],provider=rec['provider']);results.append(result)
        counts[rec['provider']][str(result['predicate_value'])]+=1
    output={'scope':'COUNTERFACTUAL_ZERO_API_GATE_DIAGNOSTIC_NOT_OFFICIAL_SCORE',
            'http_calls':0,'repairs':'Only bypassed declared gap gate; no node/quote/scope repair.',
            'outcomes':{k:dict(v) for k,v in counts.items()},'cases':results}
    (OUT/'gap_gate_replay.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in output.items() if k!='cases'}))
