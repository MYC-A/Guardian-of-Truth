"""Finite native-data training and fixed evaluation; fail closed at every gate."""
import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tarfile
import time
import traceback
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src'),str(ROOT/'scripts')]
from scripts.v5_35b_common import read,sha,write


def recovery(a,trained):
    if not (trained/'final/CHECKPOINT.json').exists():return
    archive=a.out/'final-recovery-export.tar.gz'
    with tarfile.open(archive,'w:gz',compresslevel=3) as t:
        for name in ('final','TRAINED.json','ORDER.json','START.json'):
            p=trained/name
            if p.exists():t.add(p,arcname='training-v1/layers16/'+name)
    write(a.out/'final-recovery-export.INDEX.json',dict(name=archive.name,sha256=sha(archive),bytes=archive.stat().st_size))


def run(a):
    a.out.mkdir(parents=True,exist_ok=False);active=None;phase='wait';started=time.monotonic()
    trained=a.out/'training-v1/layers16';evaluation=a.out/'evaluation-v15'
    try:
        dependency=a.lab/'v13-native-mining-20261020/mining-v1'
        queue=a.lab/'v13-native-mining-20261020/queue-v2'
        write(a.out/'START.json',dict(deadline=a.deadline,source_sha256=sha(Path(__file__)),
            protocol_sha256=sha(ROOT/'docs/judge_20261013/V15_NATIVE_RATIONALE_TRAIN_PROTOCOL.md'),
            policy='one native rationale arm, one epoch, final checkpoint only; no eval fitting'))
        while not (dependency/'DONE.json').exists():
            if (dependency/'FAIL.json').exists() or (queue/'FAIL.json').exists():raise ValueError('MINING_DEPENDENCY_FAILED')
            if time.time()>a.deadline-7200:raise TimeoutError('INSUFFICIENT_TRAIN_AND_EVAL_RESERVE')
            write(a.out/'PROGRESS.json',dict(phase=phase,seconds=time.monotonic()-started));time.sleep(30)
        # Native source preparation is CPU-only, after TRAIN scores freeze.
        def execute(name,command,deadline):
            nonlocal active,phase
            phase=name;write(a.out/'PROGRESS.json',dict(phase=name,seconds=time.monotonic()-started))
            with (a.out/(name+'.log')).open('w',buffering=1) as f:
                active=subprocess.Popen(command,stdout=f,stderr=subprocess.STDOUT,start_new_session=True,cwd=ROOT)
                code=active.wait(timeout=max(1,deadline-time.time()))
            if code:raise ValueError(name+'_EXIT:'+str(code))
            active=None
        execute('prepare',[sys.executable,str(ROOT/'scripts/v15_native_rationale.py'),'--lab',str(a.lab),'--out',str(a.out/'prepared-v1')],min(a.deadline-3600,time.time()+1200))
        archive=a.out/'data-export.tar.gz'
        with tarfile.open(archive,'w:gz',compresslevel=3) as t:t.add(a.out/'prepared-v1',arcname='prepared-v1')
        write(a.out/'data-export.INDEX.json',dict(name=archive.name,sha256=sha(archive),bytes=archive.stat().st_size))
        while subprocess.check_output(['nvidia-smi','--query-gpu=memory.used','--format=csv,noheader,nounits'],text=True).strip()!='0':
            if time.time()>a.deadline-3600:raise TimeoutError('GPU_RESERVE')
            time.sleep(10)
        trained.parent.mkdir(exist_ok=False)
        train_deadline=min(a.deadline-1800,time.time()+10800)
        execute('train',[str(a.lab/'v5-35b-20261019/venv/bin/python'),str(ROOT/'scripts/v7_train.py'),
            '--lab',str(a.lab),'--data',str(a.out/'prepared-v1'),'--out',str(trained),'--layers','16','--native-recipe',
            '--deadline',str(train_deadline-180)],train_deadline)
        meta=json.loads((trained/'TRAINED.json').read_bytes());recovery(a,trained)
        write(trained.parent/'DONE.json',dict(complete=bool(meta['epoch_complete']),training_path=str(trained),
            trained_sha256=sha(trained/'TRAINED.json'),adapter_sha256=meta['adapter_sha256']))
        from scripts.v7_control import export
        export(trained.parent)
        if not meta['epoch_complete']:raise ValueError('PARTIAL_EPOCH_ARCHIVED_NO_QUALITY_OR_PROMOTION')
        phase='evaluate';source=a.lab/'v12-transfer-20261020/evaluation-v12'
        d=json.loads((source/'DONE.json').read_bytes())
        if not d['complete'] or sha(source/'RESULTS.json')!=d['results_sha256']:raise ValueError('TRANSFER_CONTROL_DRIFT')
        label_pin=json.loads((source/'LABEL_SOURCE_PIN_BEFORE_JOIN.json').read_bytes())
        if sha(source/'labels_for_offbox.jsonl')!=label_pin['sha256'] or sha(Path(label_pin['source_path']))!=label_pin['sha256']:
            raise ValueError('PROTECTED_LABEL_SOURCE_DRIFT')
        evaluation.mkdir();(evaluation/'work').mkdir()
        for name in ('CONTROL_FROZEN.json','verifier_inputs.jsonl','predictions.csv','labels_for_offbox.jsonl','LABEL_SOURCE_PIN_BEFORE_JOIN.json','work/decisions.jsonl'):
            shutil.copyfile(source/name,evaluation/name)
        for arm,old in (('base','base'),('previous','new')):shutil.copytree(source/old,evaluation/arm)
        write(evaluation/'START.json',dict(source_sha256=sha(ROOT/'scripts/v12_transfer.py'),
            final_adapter_sha256=meta['adapter_sha256'],training_data_sha256=meta['data_sha256'],
            reused_control_predictions_sha256=sha(source/'predictions.csv'),labels_used_for_training=False))
        execute('evaluate',[sys.executable,str(ROOT/'scripts/v12_transfer.py'),'worker','--lab',str(a.lab),'--out',str(evaluation),
            '--arm','new','--training',str(trained),'--deadline',str(a.deadline-90)],a.deadline-30)
        from scripts.v12_transfer import analyse,filtered
        from scripts.v5_valid46_pipeline import metrics
        from types import SimpleNamespace
        analyse(SimpleNamespace(lab=a.lab,out=evaluation))
        result=json.loads((evaluation/'RESULTS.json').read_bytes())
        rows=read(evaluation/'labels_for_offbox.jsonl');gold={r['id']:r['label'] for r in rows}
        import csv
        with (evaluation/'predictions.csv').open(newline='') as f:pred=list(csv.DictReader(f))
        before=[int(r['label']) for r in pred];hard={i for i,r in enumerate(read(evaluation/'work/decisions.jsonl')) if r['hard']}
        values={r['position']:r for r in read(evaluation/'previous/scores.jsonl')};previous=filtered(before,hard,values)
        result['previous_v7']=metrics(rows,gold,previous)
        result['recipe']='V15_NATIVE_RATIONALE_V1';result['final_epoch_complete']=True
        result['quality_checkpoint_selection']=False;result['source_control_run']='V12'
        write(evaluation/'RESULTS.json',result)
        write(evaluation/'DONE.json',dict(complete=True,results_sha256=sha(evaluation/'RESULTS.json'),seconds=time.monotonic()-started))
        export(evaluation);write(a.out/'DONE.json',dict(complete=True,seconds=time.monotonic()-started))
    except Exception as e:
        write(a.out/'FAIL.json',dict(phase=phase,error=str(e),traceback=traceback.format_exc(),seconds=time.monotonic()-started));raise
    finally:
        if active is not None and active.poll() is None:
            os.killpg(active.pid,signal.SIGTERM)
            try:active.wait(timeout=180)
            except subprocess.TimeoutExpired:os.killpg(active.pid,signal.SIGKILL);active.wait()
        recovery(a,trained)
        from scripts.v7_control import export
        if trained.parent.exists():export(trained.parent)
        if (a.out/'FAIL.json').exists():
            evaluation.mkdir(exist_ok=True)
            shutil.copyfile(a.out/'FAIL.json',evaluation/'FAIL.json')
        if evaluation.exists() and not (a.out/'evaluation-v15-export.INDEX.json').exists():export(evaluation)
        export(a.out)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('lab','out'):p.add_argument('--'+k,type=Path,required=True)
    p.add_argument('--deadline',type=float,required=True);run(p.parse_args())
