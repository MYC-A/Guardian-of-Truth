"""Bounded supervised preparation/training, with export even on failure."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tarfile
import time

sys.path.insert(0,str(Path(__file__).resolve().parent))
from v5_35b_common import sha,write


def main():
    p=argparse.ArgumentParser();p.add_argument('--lab',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();a.out.mkdir(exist_ok=False);scripts=Path(__file__).resolve().parent
    previous=a.lab/'v5-35b-20261019';active=None;started=time.monotonic()
    def stop(_sig,_frame):
        if active is not None and active.poll() is None:
            os.killpg(active.pid,signal.SIGTERM)
            try:active.wait(timeout=150)
            except subprocess.TimeoutExpired:os.killpg(active.pid,signal.SIGKILL);active.wait()
        raise RuntimeError('SUPERVISED_CHAIN_STOP_REQUESTED')
    signal.signal(signal.SIGTERM,stop)
    def run(name,command,timeout):
        nonlocal active
        write(a.out/'PROGRESS.json',dict(phase=name,seconds=time.monotonic()-started))
        with (a.out/(name+'.log')).open('w',buffering=1) as log:
            active=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,cwd=scripts.parent,
                env=dict(os.environ,HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTHON_DOTENV_DISABLED='1',
                    PYTHONUNBUFFERED='1',TORCHINDUCTOR_COMPILE_THREADS='2',
                    TORCHINDUCTOR_CACHE_DIR=str(a.out/'compile-cache')),start_new_session=True)
            try:code=active.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(active.pid,signal.SIGTERM)
                try:active.wait(timeout=150)
                except subprocess.TimeoutExpired:os.killpg(active.pid,signal.SIGKILL);active.wait()
                raise RuntimeError('PHASE_TIMEOUT:'+name)
        active=None
        if code:raise RuntimeError('PHASE_FAILED:'+name+':'+str(code))
    write(a.out/'START.json',dict(complete=False,source_sha256=sha(Path(__file__)),
        optimizer_cap_seconds=5400,source_adapter_unchanged=True,new_private_submission=False))
    try:
        gpu=subprocess.check_output(['nvidia-smi','--query-gpu=memory.used','--format=csv,noheader,nounits'],text=True).strip()
        if gpu!='0':raise RuntimeError('GPU_BUSY')
        run('prepare',[str(a.lab/'venv/bin/python'),str(scripts/'v6_verifier_data.py'),
            '--frozen',str(a.lab/'v4-20261019/frozen-v2'),'--model',str(a.lab/'models/qwen36-awq'),
            '--eval-data',str(previous/'eval-inputs-v1'),'--out',str(a.out/'prepared')],1200)
        run('training',[str(previous/'venv/bin/python'),str(scripts/'v6_verifier_train.py'),
            '--model',str(a.lab/'models/qwen36-awq'),'--manifest',str(previous/'BASE_MODEL_MANIFEST.json'),
            '--source',str(previous/'train-recovered-v1'),'--data',str(a.out/'prepared'),
            '--out',str(a.out/'training')],6900)
        write(a.out/'TRAINING_CHAIN_DONE.json',dict(complete=True,seconds=time.monotonic()-started,
            trained=json.loads((a.out/'training/TRAINED.json').read_bytes()),evaluation_complete=False))
    except Exception as e:
        write(a.out/'FAIL.json',dict(complete=False,error=str(e),seconds=time.monotonic()-started));raise
    finally:
        archive=a.out.parent/(a.out.name+'-training-export.tar.gz')
        with tarfile.open(archive,'w:gz',compresslevel=3) as tar:
            for f in a.out.rglob('*'):
                if not f.is_file() or 'compile-cache' in f.relative_to(a.out).parts or f.name=='eval_tokens.jsonl':continue
                # Earlier update checkpoints remain on-box; export the latest committed one too on failure.
                relative=f.relative_to(a.out)
                if any(part.startswith('checkpoint-') for part in relative.parts):
                    checkpoints=sorted((a.out/'training').glob('checkpoint-*'))
                    if checkpoints and checkpoints[-1].name not in relative.parts:continue
                tar.add(f,arcname='warmstart/'+str(relative),recursive=False)
        write(a.out.parent/(a.out.name+'-training-export.INDEX.json'),dict(name=archive.name,
            bytes=archive.stat().st_size,sha256=sha(archive),training_complete=(a.out/'TRAINING_CHAIN_DONE.json').exists(),
            evaluation_complete=False))


if __name__=='__main__':main()
