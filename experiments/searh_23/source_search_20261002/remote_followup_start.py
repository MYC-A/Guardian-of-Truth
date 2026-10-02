"""Start only the explicitly authorized short frozen follow-up sequence."""
import json
from pathlib import Path
import re
import subprocess
import sys

def command(args):
    return subprocess.check_output(args,text=True).strip()

revision=sys.argv[1]
if not re.fullmatch('[0-9a-f]{8,40}',revision): raise ValueError('pinned SHA required')
base=Path('/workspace/guardian'); checkout=base/('repos/source-search-'+revision)
python=str(base/'modular_venv/bin/python')
sha=command(['git','-C',str(checkout),'rev-parse','HEAD'])
if not sha.startswith(revision): raise ValueError('SHA mismatch')
frozen={name:json.loads(command([python,str(checkout/('experiments/searh_23/source_search_20261002/'+name+'.py'))]))
        for name in ('strict_move_micro','typed_scope_probe','api_remaining_screen')}
name='guardian_source_followup_'+revision[:8]
config=Path('/etc/supervisor/conf.d')/(name+'.conf')
if config.exists(): raise ValueError('job already exists; inspect instead of restart')
out=base/('results/source-search-followup-'+revision); out.mkdir(parents=True,exist_ok=True)
names=('guardian_research','guardian_modular_20261002','guardian_source_search_376f5d14')
old={n:command(['supervisorctl','pid',n]) for n in names}
receipt={'revision':sha,'frozen':frozen,'authorized_total_tokens':1200000,'authorized_total_attempts':350,
         'authorization':'Explicit user reply on 2026-10-03','prior_ledger_preserved':True,
         'scope':'one strict parse + 18 short ablation results + 3 remaining APIs; <=34 new HTTP attempts',
         'no_full_benchmark':True}
config.write_text(f'''[program:{name}]
command={python} experiments/searh_23/source_search_20261002/followup_batch.py
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
receipt.update(program=name,old_pids_before=old,old_pids_after=after,
               status=command(['supervisorctl','status',name]))
(out/'launch.json').write_text(json.dumps(receipt,indent=2))
print(json.dumps(receipt))
