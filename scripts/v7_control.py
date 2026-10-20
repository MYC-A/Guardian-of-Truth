"""Finite own-process supervision and checkpoint export under the user's GPU deadline."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tarfile
import time
import traceback
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src'),str(ROOT/'scripts')]
from scripts.v5_35b_common import sha,write

GPU_END=1792493399.0  # 2026-10-20 10:49:59 UTC; user-authorized five-hour window.
TRAIN_END=1792486800.0  # 09:00 UTC; reserve quality evaluation/export.

def export(folder):
    archive=folder.parent/(folder.name+'-export.tar.gz')
    with tarfile.open(archive,'w:gz',compresslevel=3) as tar:
        checkpoints=sorted(folder.glob('**/checkpoint-*'))
        latest=checkpoints[-1] if checkpoints else None
        for f in folder.rglob('*'):
            if not f.is_file() or f.name=='state.pt' or 'initial-adapter' in f.parts:continue
            cp=next((p for p in f.parents if p.name.startswith('checkpoint-')),None)
            if cp is not None and cp!=latest:continue
            tar.add(f,arcname=folder.name+'/'+str(f.relative_to(folder)),recursive=False)
    write(folder.parent/(folder.name+'-export.INDEX.json'),dict(name=archive.name,bytes=archive.stat().st_size,
        sha256=sha(archive),verified_onbox=True,complete=(folder/'DONE.json').exists()))

def run(a):
    global TRAIN_END
    TRAIN_END=a.train_deadline
    a.out.mkdir(exist_ok=False);active=None;started=time.monotonic()
    def stop(_sig,_frame):
        if active is not None and active.poll() is None:
            os.killpg(active.pid,signal.SIGTERM)
            try:active.wait(timeout=120)
            except subprocess.TimeoutExpired:os.killpg(active.pid,signal.SIGKILL);active.wait()
        raise RuntimeError('SUPERVISED_STOP')
    signal.signal(signal.SIGTERM,stop)
    def execute(name,command,deadline):
        nonlocal active
        if time.time()>=deadline:raise TimeoutError('NO_PHASE_BUDGET')
        with (a.out/(name+'.log')).open('w',buffering=1) as log:
            active=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,cwd=ROOT,
                env=dict(os.environ,HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTHON_DOTENV_DISABLED='1',
                    PYTHONUNBUFFERED='1',VLLM_ALLOW_INSECURE_SERIALIZATION='1'))
            try:code=active.wait(timeout=max(1,deadline-time.time())+120)
            except subprocess.TimeoutExpired:
                stop(None,None)
            active=None
        return code
    write(a.out/'START.json',dict(phase=a.phase,gpu_deadline=GPU_END,train_deadline=TRAIN_END,source_sha256=sha(Path(__file__))))
    try:
        if a.phase=='train':
            while not (a.root/'mining-v1/DONE.json').exists():
                if time.time()>TRAIN_END-1200:raise TimeoutError('MINING_WAIT')
                time.sleep(10)
            while subprocess.check_output(['nvidia-smi','--query-gpu=memory.used','--format=csv,noheader,nounits'],text=True).strip()!='0':
                if time.time()>TRAIN_END-1200:raise TimeoutError('GPU_RELEASE_WAIT')
                time.sleep(3)
            common=[str(a.lab/'v5-35b-20261019/venv/bin/python'),str(ROOT/'scripts/v7_train.py'),
                '--lab',str(a.lab),'--data',str(a.root/'mining-v1'),'--deadline',str(TRAIN_END)]
            if a.resume_receipt is not None:
                while not a.resume_receipt.exists():
                    if time.time()>TRAIN_END-600:raise TimeoutError('RESUME_SOURCE_WAIT')
                    time.sleep(5)
                source=Path(json.loads(a.resume_receipt.read_bytes())['training_path'])/'final'
                common+=['--resume',str(source)]
            chosen=None
            for layers in ((16,) if a.resume_receipt is not None else (16,8)):
                destination=a.out/('layers'+str(layers))
                code=execute('layers'+str(layers),common+['--out',str(destination),'--layers',str(layers)],TRAIN_END)
                if code==0:
                    chosen=destination;break
                failure=json.loads((destination/'FAIL.json').read_bytes())
                if layers!=16 or failure['optimizer_updates'] or not any(s in failure['error'].lower() for s in ('out of memory','cuda error: out of memory')):
                    raise RuntimeError('TRAINING_FAILED:'+str(code))
                write(a.out/'TECHNICAL_FALLBACK.json',dict(before_any_optimizer_update=True,reason=failure['error'],layers=8))
            if chosen is None:raise RuntimeError('NO_TRAINED_CANDIDATE')
            write(a.out/'DONE.json',dict(complete=True,training_path=str(chosen),trained=json.loads((chosen/'TRAINED.json').read_bytes()),seconds=time.monotonic()-started))
        else:
            training=a.root/a.training_folder
            while not (training/'DONE.json').exists():
                if (training/'FAIL.json').exists():raise RuntimeError('TRAIN_FAILED')
                if time.time()>GPU_END-1800:raise TimeoutError('EVALUATION_WAIT')
                time.sleep(10)
            chosen=json.loads((training/'DONE.json').read_bytes())['training_path']
            while subprocess.check_output(['nvidia-smi','--query-gpu=memory.used','--format=csv,noheader,nounits'],text=True).strip()!='0':
                if time.time()>GPU_END-1800:raise TimeoutError('GPU_RELEASE_WAIT')
                time.sleep(3)
            for arm in ('base','old','new'):
                release_wait=time.monotonic()+90
                while subprocess.check_output(['nvidia-smi','--query-gpu=memory.used','--format=csv,noheader,nounits'],text=True).strip()!='0':
                    if time.monotonic()>release_wait:raise TimeoutError('PREVIOUS_ARM_GPU_NOT_RELEASED')
                    time.sleep(2)
                folder=a.out/arm;folder.mkdir()
                cmd=[str(a.lab/'venv/bin/python'),str(ROOT/'scripts/v7_evaluate.py'),'worker',
                    '--lab',str(a.lab),'--data',str(a.root/'prepared-v1'),'--new',chosen,'--out',str(folder),'--arm',arm,
                    '--deadline',str(GPU_END-180)]
                if execute(arm,cmd,GPU_END-180):raise RuntimeError('EVALUATION_FAILED:'+arm)
            from scripts.v7_evaluate import analyse
            analyse(a.root/'prepared-v1',a.out,a.lab)
            write(a.out/'DONE.json',dict(complete=True,seconds=time.monotonic()-started,results_sha256=sha(a.out/'RESULTS.json')))
    except Exception as e:
        write(a.out/'FAIL.json',dict(complete=False,error=str(e),traceback=traceback.format_exc(),seconds=time.monotonic()-started));raise
    finally:export(a.out)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('phase',choices=['train','evaluate'])
    for k in ('lab','root','out'):p.add_argument('--'+k,type=Path,required=True)
    p.add_argument('--train-deadline',type=float,default=TRAIN_END)
    p.add_argument('--resume-receipt',type=Path)
    p.add_argument('--training-folder',default='training-v1')
    run(p.parse_args())
