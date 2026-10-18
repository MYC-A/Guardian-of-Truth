"""Finite, restart-aware overnight stage controller; no model API or credentials."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import tarfile
import time

LAB=Path('/workspace/guardian-lab-20261018');BASE=LAB/'v3-20261019'
PY=LAB/'venv/bin/python';SCRIPTS=LAB/'code/scripts'
DEADLINE=datetime.datetime.fromisoformat('2026-10-19T02:18:43+00:00').timestamp()
STATE=BASE/'OVERNIGHT_STATE.json'
current=None
def write(path,value):
    tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(value,indent=2));tmp.replace(path)
def state(phase,needs_agent=False,**extra):
    record=dict(phase=phase,needs_agent=needs_agent,unix=time.time(),deadline=DEADLINE,**extra)
    write(STATE,record);print(json.dumps(record),flush=True)
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def snapshot(stage):
    folder=BASE/'overnight-backups';folder.mkdir(exist_ok=True)
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S')
    target=folder/(stamp+'-'+stage+'.tar.gz')
    candidates=['hours-candidates-v4','hours-decontam-v1','hours-machine-audit-v2','hours-pilot-v1',
                'hours-frozen-v1','MACHINE_AUDIT_REVIEW.json','OVERNIGHT_STATE.json']
    run=BASE/'hours-l1-v1'
    if run.exists():
        candidates += [str(p.relative_to(BASE)) for p in run.iterdir() if p.is_file()]
        if (run/'final/CHECKPOINT.json').exists():candidates += ['hours-l1-v1/final','hours-l1-v1/adapter']
        else:
            ready=sorted(p for p in run.glob('checkpoint-*') if (p/'CHECKPOINT.json').exists())
            if ready:candidates += [str(ready[-1].relative_to(BASE))]
    with tarfile.open(target.with_suffix('.partial'),'w:gz',compresslevel=1) as archive:
        for name in candidates:
            p=BASE/name
            if p.exists():archive.add(p,arcname=name)
        for script in sorted(SCRIPTS.glob('v3_*.py')):archive.add(script,arcname='executed_code/'+script.name)
    target.with_suffix('.partial').rename(target)
    index=folder/'INDEX.json';items=json.loads(index.read_bytes()) if index.exists() else []
    items.append(dict(name=target.name,sha256=sha(target),bytes=target.stat().st_size))
    write(index,items)
def run(phase,command,timeout):
    global current
    state(phase,command=[str(x) for x in command])
    log=BASE/(phase+'.log')
    with log.open('ab',buffering=0) as output:
        current=subprocess.Popen([str(x) for x in command],stdout=output,stderr=subprocess.STDOUT)
        started=time.time();last_backup='';last_heartbeat=0
        while current.poll() is None:
            if time.time()>DEADLINE or time.time()-started>timeout:
                current.terminate()
                try:current.wait(timeout=120)
                except subprocess.TimeoutExpired:current.kill();current.wait()
                raise TimeoutError(phase)
            if time.time()-last_heartbeat>60:
                state(phase,pid=current.pid,elapsed=time.time()-started);last_heartbeat=time.time()
                if phase=='TRAIN':
                    ready=sorted(p.name for p in (BASE/'hours-l1-v1').glob('checkpoint-*') if (BASE/'hours-l1-v1'/p.name/'CHECKPOINT.json').exists())
                    if ready and ready[-1]!=last_backup:snapshot(ready[-1]);last_backup=ready[-1]
            time.sleep(5)
        code=current.returncode;current=None
        if code:raise RuntimeError(f'{phase}: exit {code}; inspect {log}')
def main():
    lock=BASE/'OVERNIGHT_CONTROLLER.lock'
    import fcntl
    with lock.open('w') as guard:
        fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
        state('WAIT_AUDIT')
        while not (BASE/'hours-machine-audit-v2/DONE.json').exists():
            if time.time()>DEADLINE-3600:raise TimeoutError('AUDIT_NOT_DONE_IN_TIME')
            result=subprocess.run(['supervisorctl','status','guardian-lab-v3-tau-35b-audit-r2'],capture_output=True,text=True)
            if 'EXITED' in result.stdout or 'FATAL' in result.stdout:
                raise RuntimeError('AUDIT_JOB_ENDED_WITHOUT_DONE: '+result.stdout.strip())
            state('WAIT_AUDIT')
            time.sleep(15)
        state('WAIT_SOURCE_REVIEW',needs_agent=True)
        while not (BASE/'MACHINE_AUDIT_REVIEW.json').exists():
            if time.time()>DEADLINE-3600:raise TimeoutError('SOURCE_REVIEW_NOT_DONE')
            state('WAIT_SOURCE_REVIEW',needs_agent=True)
            time.sleep(15)
        review=json.loads((BASE/'MACHINE_AUDIT_REVIEW.json').read_bytes())
        assert review['allow_exploratory_training'] and not review['human_reviewed']
        assert review['candidate_sha256']==sha(BASE/'hours-decontam-v1/candidate_rows.jsonl')
        # Wait for inference server's supervisor process to exit and release GPU.
        for _ in range(60):
            status=subprocess.run(['supervisorctl','status','guardian-lab-v3-tau-35b-audit-r2'],capture_output=True,text=True).stdout
            if 'RUNNING' not in status:break
            time.sleep(2)
        else:raise RuntimeError('35B_SERVER_NOT_RELEASED')
        snapshot('pretraining')
        pilot=BASE/'hours-pilot-v1'
        if not (pilot/'DONE.json').exists():
            assert not pilot.exists(),'PILOT_PARTIAL_REQUIRES_REVIEW'
            run('PILOT',[PY,SCRIPTS/'v3_train_hours.py','--pilot','--model',LAB/'models/qwen3-4b-instruct',
                '--data',BASE/'hours-decontam-v1','--out',pilot],900)
        frozen=BASE/'hours-frozen-v1'
        budget=int(min(10800,max(0,(DEADLINE-time.time())*.75-180)))
        assert budget>=1800,'NOT_ENOUGH_TRAIN_EVAL_TIME'
        if not (frozen/'FROZEN.json').exists():
            assert not frozen.exists(),'FREEZE_PARTIAL_REQUIRES_REVIEW'
            run('FREEZE',[PY,SCRIPTS/'v3_freeze_hours_split.py','--data',BASE/'hours-decontam-v1/candidate_rows.jsonl',
                '--pilot',pilot/'DONE.json','--out',frozen,'--training-seconds',str(budget)],300)
        run_folder=BASE/'hours-l1-v1'
        if not (run_folder/'DONE.json').exists():
            assert not run_folder.exists(),'PARTIAL_TRAIN_REQUIRES_EXPLICIT_CHECKPOINT_RESUME_REVIEW'
            run('TRAIN',[PY,SCRIPTS/'v3_train_hours.py','--model',LAB/'models/qwen3-4b-instruct',
                '--data',frozen,'--out',run_folder,'--budget-seconds',str(budget),
                '--real-input',LAB/'data/guardian-judge-eval-data-v1/regression_seen/inputs.csv'],max(1,int(DEADLINE-time.time())))
        snapshot('trained-evaluated');state('READY_FOR_ANALYSIS',needs_agent=True)

def stop(_sig,_frame):
    if current is not None and current.poll() is None:
        current.terminate()
        try:current.wait(timeout=120)
        except subprocess.TimeoutExpired:current.kill()
    raise SystemExit('Controller terminated; preserve partial artifacts')

if __name__=='__main__':
    os.environ.update(PYTHON_DOTENV_DISABLED='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    signal.signal(signal.SIGTERM,stop)
    try:main()
    except BaseException as exc:
        state('NEEDS_REVIEW',needs_agent=True,error_type=type(exc).__name__,error=str(exc)[:800])
        try:snapshot('interrupted')
        except Exception:pass
        raise
