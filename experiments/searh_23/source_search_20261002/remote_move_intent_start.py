"""User-approved resume excluding Vireonix; retain breaker and ledger audit."""
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
if not sha.startswith(revision): raise ValueError('checkout SHA mismatch')
frozen=json.loads(command([python,str(checkout/'experiments/searh_23/source_search_20261002/move_intent_probe.py')]))
name='guardian_move_intent_'+revision[:8]
config=Path('/etc/supervisor/conf.d')/(name+'.conf')
if config.exists(): raise ValueError('job already exists; never restart blindly')
phase=base/'results/source-search-api-phase-20261002'
breaker=phase/'breaker.json'
record=None
if breaker.exists():
    record=json.loads(breaker.read_text())
    if record.get('http_status')!=403:
        raise ValueError('approval excludes only Vireonix 403; never clear another error')
    remaining=base/'repos/source-search-434f3ccb/outputs/searh_23/source_search_20261002/api_remaining_screen_v1/results.jsonl'
    records=[json.loads(line) for line in remaining.read_text().splitlines()]
    last_attempt=json.loads((phase/'attempts.jsonl').read_text().splitlines()[-1])
    expected=records[-1]
    if (expected['provider']!='vireonix' or expected['raw_record'].get('http_status')!=403
            or last_attempt.get('request_sha256')!=expected['raw_record']['request_sha256']):
        raise ValueError('breaker not established as the excluded Vireonix request')
    archived=phase/'breaker_403_vireonix_user_approved_resume_20261003.json'
    if archived.exists(): raise ValueError('resume receipt already exists; inspect first')
    breaker.rename(archived)
out=base/('results/move-intent-'+revision); out.mkdir(parents=True,exist_ok=True)
names=('guardian_research','guardian_modular_20261002','guardian_source_search_376f5d14')
old={n:command(['supervisorctl','pid',n]) for n in names}
receipt={'revision':sha,'frozen':frozen,'authorization':'Explicit user approval to exclude Vireonix and continue 2026-10-03',
         'prior_breaker':record,'limits':{'total_tokens':1200000,'total_attempts':350},
         'no_counters_reset':True,'max_new_attempts':8,'provider':'mistral'}
config.write_text(f'''[program:{name}]
command={python} experiments/searh_23/source_search_20261002/move_intent_probe.py --run
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
if old!=after: raise ValueError('existing service PID changed')
receipt.update(program=name,status=command(['supervisorctl','status',name]),
               old_pids_before=old,old_pids_after=after)
(out/'launch.json').write_text(json.dumps(receipt,indent=2)); print(json.dumps(receipt))
