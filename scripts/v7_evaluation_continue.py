"""Reuse the completed control, prioritize new LoRA, finish all three arms."""
import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import traceback
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src'),str(ROOT/'scripts')]
from scripts.v5_35b_common import read,sha,write
from scripts.v7_control import export

def verify_base(folder,prepared,protocol_sha):
    receipt=json.loads((folder/'DONE.json').read_bytes())
    if not receipt['complete'] or receipt['arm']!='base' or receipt['rows']!=757 or receipt['input_sha256']!=prepared['eval_tokens_sha256']:
        raise ValueError('INCOMPLETE_OR_DIFFERENT_BASE')
    if receipt['eval_protocol_sha256']!=protocol_sha or not receipt['all_admitted_scores_exact'] or receipt['valid46_measurements']!=3:
        raise ValueError('BASE_PROTOCOL_OR_EXACT_DRIFT')
    for name in ('scores','repeat_scores'):
        if sha(folder/(name+'.jsonl'))!=receipt[name+'_sha256']:raise ValueError('BASE_FILE_DRIFT')
    return receipt

def run(a):
    a.out.mkdir(exist_ok=False);active=None;started=time.monotonic()
    def stop(_sig,_frame):
        if active is not None and active.poll() is None:
            os.killpg(active.pid,signal.SIGTERM)
            try:active.wait(timeout=90)
            except subprocess.TimeoutExpired:os.killpg(active.pid,signal.SIGKILL);active.wait()
        raise RuntimeError('SUPERVISED_STOP')
    signal.signal(signal.SIGTERM,stop)
    data=a.root/'prepared-v1';source=a.root/'evaluation-v2'
    try:
        prepared=json.loads((data/'PREPARED.json').read_bytes())
        base=verify_base(source/'base',prepared,sha(data/'EVAL_PROTOCOL.json'))
        frozen=json.loads((source/'EVAL_CODE_FROZEN.json').read_bytes())
        if sha(ROOT/'scripts/v7_evaluate.py')!=frozen['evaluator_sha256'] or sha(ROOT/'scripts/v5_valid46_pipeline.py')!=frozen['binding_sha256']:
            raise ValueError('SCORING_CODE_CHANGED')
        shutil.copytree(source/'base',a.out/'base')
        verify_base(a.out/'base',prepared,sha(data/'EVAL_PROTOCOL.json'))
        shutil.copy2(source/'EVAL_CODE_FROZEN.json',a.out/'EVAL_CODE_FROZEN.json')
        write(a.out/'START.json',dict(source_sha256=sha(Path(__file__)),gpu_deadline=a.deadline,
            reused_completed_base=True,source_base_done_sha256=sha(source/'base/DONE.json'),
            scoring_code_unchanged=True,remaining_arm_order=['new','old'],
            reason='User extended GPU to 14:30 MSK; prioritize requested new adapter',
            partial_old_arm_not_used_as_complete=True,quality_metrics_used_for_change=False))
        trained=json.loads((a.root/'training-v2/DONE.json').read_bytes())
        if not trained['complete'] or not trained['trained']['epoch_complete'] or trained['trained']['rows_done']!=224:
            raise ValueError('FULL_TRAIN_NOT_PROVEN')
        for arm in ('new','old'):
            release=time.monotonic()+120
            while subprocess.check_output(['nvidia-smi','--query-gpu=memory.used','--format=csv,noheader,nounits'],text=True).strip()!='0':
                if time.monotonic()>release:raise TimeoutError('GPU_NOT_RELEASED')
                time.sleep(2)
            folder=a.out/arm;folder.mkdir()
            command=[str(a.lab/'venv/bin/python'),str(ROOT/'scripts/v7_evaluate.py'),'worker',
                '--lab',str(a.lab),'--data',str(data),'--new',trained['training_path'],
                '--out',str(folder),'--arm',arm,'--deadline',str(a.deadline-180)]
            with (a.out/(arm+'.log')).open('w',buffering=1) as log:
                active=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,cwd=ROOT,
                    env=dict(os.environ,VLLM_ALLOW_INSECURE_SERIALIZATION='1',HF_HUB_OFFLINE='1',
                        TRANSFORMERS_OFFLINE='1',PYTHON_DOTENV_DISABLED='1',PYTHONUNBUFFERED='1'))
                try:code=active.wait(timeout=max(1,a.deadline-180-time.time())+90)
                except subprocess.TimeoutExpired:stop(None,None)
                active=None
            if code:raise RuntimeError('ARM_FAILED:'+arm+':'+str(code))
        from scripts.v7_evaluate import analyse
        result=analyse(data,a.out,a.lab)
        write(a.out/'DONE.json',dict(complete=True,results_sha256=sha(a.out/'RESULTS.json'),
            seconds=time.monotonic()-started,gate_passed=result['offline_gate']['passed'],
            reused_base_arm=True,all_arms_complete=True))
    except Exception as e:
        write(a.out/'FAIL.json',dict(error=str(e),traceback=traceback.format_exc(),seconds=time.monotonic()-started));raise
    finally:export(a.out)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('lab','root','out'):p.add_argument('--'+k,type=Path,required=True)
    p.add_argument('--deadline',type=float,required=True);run(p.parse_args())
