"""Deploy only this experiment's files and own supervised finite jobs."""
import argparse
import base64
import json
from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[1]
REMOTE='/workspace/guardian-lab-20261018/v7-workflow-20261020'
SSH=['C:/Program Files/Git/usr/bin/ssh.exe','-i','C:/Users/Igor/.ssh/guardian_vast_me','-p','18293','root@209.137.198.14']

def remote(source):
    p=subprocess.run(SSH+['python3 -'],input=source,text=True,encoding='utf-8',capture_output=True)
    print(p.stdout);print(p.stderr)
    if p.returncode:raise SystemExit(p.returncode)

def run(a):
    names=['scripts/v7_workflow_data.py','scripts/v7_prepare.py','scripts/v5_35b_common.py','scripts/v5_valid46_pipeline.py']
    names+=a.file
    payload={n:base64.b64encode((ROOT/n).read_bytes()).decode() for n in names}
    code=f'''
from pathlib import Path
import base64,json,shutil,subprocess
root=Path({REMOTE!r});root.mkdir(exist_ok=True)
code=root/{a.code!r}
if not code.exists():shutil.copytree('/workspace/guardian-lab-20261018/v6-verifier-20261020/code-eval-27e6ee0f',code)
for name,value in json.loads({json.dumps(json.dumps(payload))}).items():
    (code/name).write_bytes(base64.b64decode(value))
print('CODE_UPDATED',str(code))
'''
    if a.phase=='prepare':
        revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
        command=f'/workspace/guardian-lab-20261018/venv/bin/python {REMOTE}/{a.code}/scripts/v7_prepare.py --lab /workspace/guardian-lab-20261018 --out {REMOTE}/prepared-v1 --revision {revision}'
    elif a.phase=='command':command=a.command
    else:remote(code);return
    wrapper=f'/opt/supervisor-scripts/{a.name}.sh';config=f'/etc/supervisor/conf.d/{a.name}.conf'
    body='#!/bin/bash\nset -e\ncd '+REMOTE+'/'+a.code+'\nexport HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONUNBUFFERED=1 PYTHON_DOTENV_DISABLED=1 VLLM_ALLOW_INSECURE_SERIALIZATION=1\nexec '+command+'\n'
    conf=f'[program:{a.name}]\nenvironment=PROC_NAME="%(program_name)s"\ncommand={wrapper}\nautostart=false\nautorestart=false\nstartretries=0\nstartsecs=3\nstopwaitsecs=180\nstopasgroup=true\nkillasgroup=true\nstdout_logfile={REMOTE}/{a.name}.log\nredirect_stderr=true\nstdout_logfile_maxbytes=0\n'
    code+=f'''
wrapper=Path({wrapper!r});conf=Path({config!r})
if wrapper.exists() or conf.exists():raise ValueError('JOB_ALREADY_EXISTS')
wrapper.write_text({body!r});wrapper.chmod(0o755);conf.write_text({conf!r})
for cmd in (['supervisorctl','reread'],['supervisorctl','update',{a.name!r}],['supervisorctl','start',{a.name!r}],['supervisorctl','status',{a.name!r}]):
    subprocess.run(cmd,check=True)
'''
    remote(code)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('phase',choices=['prepare','command','update'])
    p.add_argument('--code',default='code-v1');p.add_argument('--file',action='append',default=[])
    p.add_argument('--name',default='guardian-lab-v7-prepare-v1');p.add_argument('--command',default='')
    run(p.parse_args())
