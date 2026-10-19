"""Wait for the current finite segment, then continue the single frozen epoch."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parent))
from v5_35b_common import sha, write


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--root',type=Path,required=True)
    a=p.parse_args();r=a.root;s=Path(__file__).resolve().parent
    out=r/'full-followup-v1';out.mkdir(exist_ok=False);started=time.monotonic()
    prior=r/'resume-v2';training=r/'train-full-v1';py=r/'venv/bin/python'
    write(out/'START.json',dict(authority='User explicitly approved completing one full pass after the measured speedup',
        total_optimizer_safety_budget_seconds=57600,additional_epochs=0,prior_training=str(prior),
        source_sha256=sha(Path(__file__)),quality_selection=False))
    try:
        while not (prior/'TRAINED.json').exists():
            status=subprocess.run(['supervisorctl','status','guardian-lab-v5-35b-resume-v2'],capture_output=True,text=True)
            if (prior/'FAIL.json').exists() or any(x in status.stdout for x in ('EXITED','FATAL','STOPPED')):
                raise RuntimeError('PRIOR_SEGMENT_FAILED:'+status.stdout)
            if time.monotonic()-started>14400:raise TimeoutError('PRIOR_SEGMENT_WAIT_DEADLINE')
            time.sleep(20)
        rec=json.loads((prior/'TRAINED.json').read_bytes())
        for _ in range(120):
            gpu=subprocess.check_output(['nvidia-smi','--query-gpu=memory.used','--format=csv,noheader,nounits'],text=True).strip()
            if gpu=='0':break
            time.sleep(1)
        else:raise RuntimeError('PREVIOUS_TRAINING_GPU_NOT_RELEASED')
        if rec['epoch_complete']:
            if rec['rows_done']!=1458:raise ValueError('COMPLETE_ROWS_MISMATCH')
            training.mkdir(exist_ok=False)
            for name in ('START.json','MODEL_READY.json','LOADER_COMPATIBILITY.json','TRAINED.json','PROGRESS.json'):
                if (prior/name).exists():shutil.copy2(prior/name,training/name)
            for name in ('adapter','final'):shutil.copytree(prior/name,training/name)
            write(out/'DONE.json',dict(complete=True,epoch_complete=True,rows_done=1458,no_second_epoch=True))
            return
        cmd=[str(py),str(s/'v5_35b_resume_watch.py'),'--out',str(r/'resume-launch-full-v1'),
             '--training',str(training),'--timeout-seconds','28800','--require-full-epoch','--',str(py),str(s/'v5_35b_resume.py'),
             '--model',str(r.parent/'models/qwen36-awq'),'--manifest',str(r/'BASE_MODEL_MANIFEST.json'),
             '--data',str(r/'prepared-v1'),'--gate',str(r/'TRAINING_PROFILE.json'),'--resume',str(prior/'final'),
             '--out',str(training),'--benchmark',str(r/'dequant-benchmark-v1/DONE.json'),
             '--total-budget-seconds','57600']
        write(out/'CONTINUING.json',dict(command=cmd,prior_rows=rec['rows_done'],prior_steps=rec['optimizer_updates']))
        # Replace this waiter in the same supervised group; no detached trainer.
        os.execv(str(py),cmd)
    except Exception as e:
        write(out/'FAIL.json',dict(complete=False,error=str(e),seconds=time.monotonic()-started));raise


if __name__=='__main__':main()
