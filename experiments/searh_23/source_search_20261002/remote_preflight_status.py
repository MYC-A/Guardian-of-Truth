"""One read-only snapshot of the finite job, with no provider requests."""
import json
from pathlib import Path
import subprocess
import sys

revision=sys.argv[1]
repo=Path('/workspace/guardian/repos')/('source-search-'+revision)
sys.path.insert(0,str(repo/'experiments/searh_23/source_search_20261002'))
from model_preflight import OUT, PHASE
from guardian_truth.source_search.transport import ModelTransport

journal=OUT/'predictions.jsonl'
rows=[json.loads(line) for line in journal.read_text().splitlines()] if journal.exists() else []
state=subprocess.run(['supervisorctl','status','guardian_source_preflight_'+revision[:8]],text=True,capture_output=True)
print(json.dumps({'process':state.stdout.strip(), 'supervisor_exit':state.returncode,
    'records':len(rows),'summary':[{'id':r['case_id'],'model':r['model'],'mode':r['mode'],
        'decision':r['decision'],'stop':r['stop_reason'],'steps':len(r['trace']),
        'operations':[t.get('action',{}).get('action',{}).get('op') for t in r['trace'] if t.get('action')]} for r in rows],
    'budget':ModelTransport(PHASE,max_calls=300,max_tokens=1000000).snapshot(),
    'status':json.loads((OUT/'status.json').read_text()) if (OUT/'status.json').exists() else None}))
