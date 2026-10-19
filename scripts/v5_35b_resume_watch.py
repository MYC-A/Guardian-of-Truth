"""Finite supervised resume with hourly health receipts."""
import argparse
import json
import math
from pathlib import Path
import subprocess
import time
import sys

from v5_35b_common import write


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--training',type=Path,required=True)
    p.add_argument('command',nargs=argparse.REMAINDER)
    a=p.parse_args();a.out.mkdir(exist_ok=False)
    command=a.command[1:] if a.command[:1]==['--'] else a.command
    started=time.monotonic()
    write(a.out/'START.json',dict(command=command,timeout_seconds=14400,hourly_check_seconds=3600))
    try:
        with (a.out/'training.log').open('w',buffering=1) as stream:
            child=subprocess.Popen(command,stdout=stream,stderr=subprocess.STDOUT)
            previous=None;checks=0
            while child.poll() is None:
                try:child.wait(timeout=min(3600,max(.1,14400-(time.monotonic()-started))))
                except subprocess.TimeoutExpired:
                    if time.monotonic()-started>=14400:raise TimeoutError('RESUME_FINITE_DEADLINE')
                    checks+=1
                    prog=json.loads((a.training/'PROGRESS.json').read_bytes())
                    healthy=(math.isfinite(prog['loss']) and math.isfinite(prog['grad_norm']) and
                        (previous is None or prog['rows_done']>previous) and not (a.training/'FAIL.json').exists())
                    receipt=dict(check=checks,unix=time.time(),healthy=healthy,progress=prog,process_alive=child.poll() is None,
                        fail_file=(a.training/'FAIL.json').exists(),gpu=subprocess.check_output(['nvidia-smi','--query-gpu=utilization.gpu,memory.used,memory.total','--format=csv,noheader'],text=True).strip())
                    write(a.out/('HEALTH_HOUR_%02d.json'%checks),receipt);write(a.out/'HEALTH_LATEST.json',receipt)
                    previous=prog['rows_done']
                    if not healthy:raise RuntimeError('RESUME_HOURLY_HEALTH_FAILED')
            if child.returncode:raise RuntimeError('RESUME_PROCESS_FAILED:'+str(child.returncode))
            write(a.out/'DONE.json',dict(complete=True,seconds=time.monotonic()-started))
    except Exception as e:
        if 'child' in locals() and child.poll() is None:
            child.terminate()
            try:child.wait(timeout=90)
            except subprocess.TimeoutExpired:child.kill();child.wait(timeout=30)
        write(a.out/'FAIL.json',dict(complete=False,error=str(e),seconds=time.monotonic()-started));raise


if __name__=='__main__':main()
