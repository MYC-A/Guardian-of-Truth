"""Aggregate persisted API responses and package versions, never env secrets."""
from __future__ import annotations
import importlib.metadata
import json
import platform
import statistics
from collections import Counter
from pathlib import Path
HERE=Path(__file__).parent

def run():
    result={}
    for root in ('outputs','outputs_fixed','outputs_gold','outputs_rescue'):
        usage=Counter(); served=Counter(); latency=[]; count=0
        for path in (HERE/root/'_cache').glob('*.json'):
            r=json.loads(path.read_text(encoding='utf-8')); count+=1
            served[r.get('served_model','not_saved')]+=1
            for k in ('prompt_tokens','completion_tokens','total_tokens'): usage[k]+=r.get('usage',{}).get(k,0)
            if 'latency' in r: latency.append(r['latency'])
        ordered=sorted(latency)
        result[root]={'persisted_responses':count,'token_usage':dict(usage),'served_models':dict(served),
                      'request_latency_median_s':statistics.median(latency) if latency else None,
                      'request_latency_p95_s':ordered[int(.95*(len(ordered)-1))] if ordered else None}
    versions={}
    for name in ('torch','transformers','sentence-transformers','stanza','peft','accelerate'):
        try: versions[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: versions[name]='not_installed'
    data={'environment':{'python':platform.python_version(),'packages':versions},'cache_roots':result,
          'limits':['persisted responses only; lost/unrecorded retries are excluded',
                    'latencies exclude intentional API pacing and whole-experiment wall time',
                    'GPU training peak memory was not instrumented; no peak figure is claimed',
                    'currency cost not estimated without pinned provider tariff']}
    (HERE/'resource_summary.json').write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(data,indent=2))
if __name__=='__main__': run()
