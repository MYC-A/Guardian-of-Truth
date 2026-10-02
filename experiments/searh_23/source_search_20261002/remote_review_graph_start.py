"""Launch one frozen eight-call Mistral reviewer/graph diagnostic."""
import json
from pathlib import Path
import re
import subprocess
import sys

def command(args): return subprocess.check_output(args,text=True).strip()

revision=sys.argv[1]
if not re.fullmatch('[0-9a-f]{8,40}',revision): raise ValueError('pinned SHA required')
base=Path('/workspace/guardian'); checkout=base/('repos/source-search-'+revision)
python=str(base/'modular_venv/bin/python')
sha=command(['git','-C',str(checkout),'rev-parse','HEAD'])
if not sha.startswith(revision): raise ValueError('SHA mismatch')
if (base/'results/source-search-api-phase-20261002/breaker.json').exists():
    raise ValueError('provider breaker is open; no automatic resume')
frozen=json.loads(command([python,str(checkout/'experiments/searh_23/source_search_20261002/review_graph_probe.py')]))
name='guardian_review_graph_'+revision[:8]
config=Path('/etc/supervisor/conf.d')/(name+'.conf')
if config.exists(): raise ValueError('job already exists')
out=base/('results/review-graph-'+revision); out.mkdir(parents=True,exist_ok=True)
names=('guardian_research','guardian_modular_20261002','guardian_source_search_376f5d14')
old={n:command(['supervisorctl','pid',n]) for n in names}
receipt={'revision':sha,'frozen':frozen,'authorized_total_tokens':1200000,'authorized_total_attempts':350,
         'max_new_attempts':8,'prior_ledger_preserved':True,'model':'SERVER_MISTRAL_MODEL',
         'scope':'per-finding review and actual BFS/DFS, short authored inputs, no full benchmark'}
config.write_text(f'''[program:{name}]
command={python} experiments/searh_23/source_search_20261002/review_graph_probe.py --run
directory={checkout}
autostart=true
autorestart=false
startsecs=0
stopasgroup=true
killasgroup=true
stdout_logfile={out}/run.log
stderr_logfile={out}/run.err.log
''')
subprocess.run(['supervisorctl','reread'],check=True,capture_output=True)
subprocess.run(['supervisorctl','update',name],check=True,capture_output=True)
after={n:command(['supervisorctl','pid',n]) for n in names}
if old!=after: raise ValueError('existing PID changed')
receipt.update(program=name,status=command(['supervisorctl','status',name]),old_pids_before=old,old_pids_after=after)
(out/'launch.json').write_text(json.dumps(receipt,indent=2)); print(json.dumps(receipt))
