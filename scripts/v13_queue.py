"""Finite dependency queue; starts only our TRAIN mining after complete transfer."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import traceback
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from scripts.v5_35b_common import write,sha


def run(a):
    a.out.mkdir(parents=True,exist_ok=False);active=None;started=time.monotonic()
    try:
        dependency=a.lab/'v12-transfer-20261020/evaluation-v12'
        prepared=a.out.parent/'prepared-v2'
        write(a.out/'START.json',dict(deadline=a.deadline,dependency=str(dependency),
            source_sha256=sha(Path(__file__)),purpose='TRAIN-only mining; training not scheduled'))
        while True:
            if (dependency/'FAIL.json').exists():raise ValueError('TRANSFER_FAILED_REQUIRES_REVIEW')
            if time.time()>a.deadline-1000:raise TimeoutError('DEPENDENCY_BUDGET_EXPIRED')
            ready=(dependency/'DONE.json').exists() and (prepared/'PREPARED.json').exists()
            if ready:
                d=json.loads((dependency/'DONE.json').read_bytes())
                if not d['complete'] or sha(dependency/'RESULTS.json')!=d['results_sha256']:raise ValueError('DEPENDENCY_DRIFT')
                gpu=subprocess.check_output(['nvidia-smi','--query-gpu=memory.used','--format=csv,noheader,nounits'],text=True).strip()
                if gpu=='0':break
            write(a.out/'PROGRESS.json',dict(phase='waiting_for_transfer_and_gpu',seconds=time.monotonic()-started))
            time.sleep(30)
        command=[sys.executable,str(ROOT/'scripts/v13_native_mining.py'),'mine','--lab',str(a.lab),
            '--data',str(prepared),'--out',str(a.out.parent/'mining-v1'),'--deadline',str(a.deadline-90)]
        with (a.out/'mining.log').open('w',buffering=1) as f:
            active=subprocess.Popen(command,stdout=f,stderr=subprocess.STDOUT,start_new_session=True,cwd=ROOT)
            result=active.wait(timeout=max(1,a.deadline-60-time.time()))
        if result:raise ValueError('MINING_EXIT:'+str(result))
        write(a.out/'DONE.json',dict(complete=True,seconds=time.monotonic()-started))
    except Exception as e:
        write(a.out/'FAIL.json',dict(error=str(e),traceback=traceback.format_exc()));raise
    finally:
        if active is not None and active.poll() is None:
            os.killpg(active.pid,signal.SIGTERM)
            try:active.wait(timeout=30)
            except subprocess.TimeoutExpired:os.killpg(active.pid,signal.SIGKILL);active.wait()


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('lab','out'):p.add_argument('--'+k,type=Path,required=True)
    p.add_argument('--deadline',type=float,required=True);run(p.parse_args())
