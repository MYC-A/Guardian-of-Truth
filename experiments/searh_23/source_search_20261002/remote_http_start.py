"""Separate loopback API on pinned comparison code; leave old services alone."""
import json
from pathlib import Path
import re
import socket
import subprocess
import sys

revision = sys.argv[1]
if not re.fullmatch('[0-9a-f]{8,40}', revision):
    raise ValueError('commit SHA required')
base = Path('/workspace/guardian')
checkout = base / ('repos/source-search-' + revision)
sha = subprocess.check_output(['git','-C',str(checkout),'rev-parse','HEAD'],text=True).strip()
if not sha.startswith(revision):
    raise ValueError('pinned checkout mismatch')
port = int(sys.argv[2]) if len(sys.argv) > 2 else 18094
if not 1024 <= port <= 65535:
    raise ValueError('unprivileged TCP port required')
name = 'guardian_source_search_' + revision[:8]
path = Path('/etc/supervisor/conf.d') / (name + '.conf')
if path.exists():
    raise RuntimeError('service already exists; inspect, do not overwrite')
with socket.socket() as sock:
    sock.bind(('127.0.0.1',port))
old = {n: subprocess.check_output(['supervisorctl','pid',n],text=True).strip()
       for n in ('guardian_research','guardian_modular_20261002')}
out = base / ('results/source-search-' + revision)
out.mkdir(parents=True,exist_ok=True)
path.write_text(f'''[program:{name}]
command={base}/modular_venv/bin/python -m uvicorn service.app:app --host 127.0.0.1 --port {port}
directory={checkout}
autostart=true
autorestart=unexpected
startsecs=3
stopasgroup=true
killasgroup=true
stdout_logfile={out}/http.log
stderr_logfile={out}/http.err.log
environment=GUARDIAN_CONFIG="source-search-v1",GUARDIAN_AUDIT_PATH="{out}/http_audit.jsonl",GUARDIAN_MAX_QUEUE="4",GUARDIAN_WORKERS="1"
''')
subprocess.run(['supervisorctl','reread'],check=True,capture_output=True)
subprocess.run(['supervisorctl','update',name],check=True,capture_output=True)
after = {n: subprocess.check_output(['supervisorctl','pid',n],text=True).strip() for n in old}
if old != after:
    raise RuntimeError('unexpected old PID change')
receipt={'revision':sha,'program':name,'port':port,'bind':'127.0.0.1',
    'old_pids_before':old,'old_pids_after':after,'budget_shared_with_comparison':True,
    'status':subprocess.check_output(['supervisorctl','status',name],text=True).strip()}
(out/'http_launch.json').write_text(json.dumps(receipt,indent=2))
print(json.dumps(receipt))
