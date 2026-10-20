"""Final-checkpoint regression vetoes; no checkpoint/threshold selection."""
import argparse
import csv
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import traceback
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src'),str(ROOT/'scripts')]
from scripts.v5_35b_common import read,sha,write
from scripts.v5_valid46_pipeline import metrics
from guardian_truth.judge.decision import decide


def apply_veto(rows,before,hard,values):
    if set(values)!={r['id'] for r in rows}:raise ValueError('COHORT_SCORE_JOIN')
    gold={r['id']:r['label'] for r in rows}
    after=[int(bool(y) and (i in hard or not values[r['id']]['admitted'] or values[r['id']]['score']>0)) if y else 0
           for i,(r,y) in enumerate(zip(rows,before))]
    return dict(before=metrics(rows,gold,before),after=metrics(rows,gold,after),
        removed_fp=sum(x and not y and not r['label'] for r,x,y in zip(rows,before,after)),
        lost_tp=sum(x and not y and r['label'] for r,x,y in zip(rows,before,after)))


def analyse(a,source):
    metadata=json.loads((source/'EVAL_INDEX.json').read_bytes())['rows'];values={r['id']:r for r in read(a.out/'new/scores.jsonl')}
    rows=[r for r in metadata if r['id'] in values]
    if len(values)!=757 or len(rows)!=757:raise ValueError('FINAL_REGRESSION_COVERAGE')
    def subset(scores):return {r['id']:values[r['id']] for r in scores}
    result=dict(complete=True,final_checkpoint_only=True,threshold=0,quota_refill=False,
        independent_validation=False,private_improvement_measured=False,production_promoted=False,views={})
    # The current full open/MAX dev520 pool, not historical overall-only scores.
    dev=[r for r in rows if 'dev520' in r['cohorts']];lookup={r['original_id']:r for r in dev}
    v10=a.lab/'v10-full-profile-batch64-20261020/evaluation-v10';d=read(v10/'work/decisions.jsonl')
    with (v10/'predictions.csv').open(newline='') as f:pred=list(csv.DictReader(f))
    if len(d)!=520 or [r['id'] for r in d]!=[r['id'] for r in pred]:raise ValueError('DEV_CONTROL_ORDER')
    ordered=[lookup[r['id']] for r in pred];before=[int(r['label']) for r in pred];hard={i for i,r in enumerate(d) if r['hard']}
    result['views']['dev520_full_MAX_40']=apply_veto(ordered,before,hard,subset(ordered))
    # Historical real191 overall-only, explicitly not a full best-ZIP control.
    real=[r for r in rows if 'real191' in r['cohorts']];hard={i for i,r in enumerate(real) if r['hard']}
    old=a.lab/'v5-35b-20261019/finish-v6/paired-native';receipt=json.loads((old/'WORKER_DONE.json').read_bytes())
    if sha(old/'scores.jsonl')!=receipt['scores_sha256']:raise ValueError('HISTORICAL_SCORE_DRIFT')
    scores={r['id']:r['score'] for r in read(old/'scores.jsonl') if r['arm']=='base'}
    before=decide(len(real),hard,{i:scores[r['id']] for i,r in enumerate(real)},.4)
    result['views']['real191_historical_overall_only_40']=apply_veto(real,before,hard,subset(real))
    best=read(a.lab/'v5-35b-20261019/pipeline-valid46-v4/base/work/decisions.jsonl')
    lookup={r['original_id']:r for r in rows if 'valid46' in r['cohorts']};valid=[lookup[r['id']] for r in best]
    if len(valid)!=46:raise ValueError('VALID_CONTROL_COUNT')
    hard={r['key'] for r in best if r['hard']};ranked={r['key']:r['ranked_by'] for r in best}
    for rate in (.4,.7):
        before=decide(46,hard,ranked,rate)
        result['views']['valid46_historical_best_MAX_'+str(int(100*rate))]=apply_veto(valid,before,hard,subset(valid))
    result['scores_sha256']=sha(a.out/'new/scores.jsonl')
    write(a.out/'RESULTS.json',result)


def run(a):
    a.out.mkdir(parents=True,exist_ok=False);active=None;started=time.monotonic()
    def stop(_sig,_frame):raise RuntimeError('SUPERVISED_FINAL_REGRESSION_STOP')
    signal.signal(signal.SIGTERM,stop)
    try:
        v15=a.candidate_root or a.lab/'v15-native-rationale-20261020-v3';trained=v15/'training-v1/layers16'
        write(a.out/'START.json',dict(source_sha256=sha(Path(__file__)),
            protocol_sha256=sha(ROOT/'docs/judge_20261013/V16_FINAL_REGRESSION_PROTOCOL.md'),deadline=a.deadline,
            final_checkpoint_only=True,no_quality_selection=True,phase='waiting'))
        while not (v15/'DONE.json').exists():
            if (v15/'FAIL.json').exists():raise ValueError('NATIVE_CANDIDATE_FAILED_GATES')
            if time.time()>a.deadline-1500:raise TimeoutError('FINAL_REGRESSION_WAIT_LIMIT')
            time.sleep(30)
        while subprocess.check_output(['nvidia-smi','--query-gpu=memory.used','--format=csv,noheader,nounits'],text=True).strip()!='0':
            if time.time()>a.deadline-1400:raise TimeoutError('GPU_RELEASE_LIMIT')
            time.sleep(10)
        source=a.lab/'v7-workflow-20261020/prepared-v1';meta=json.loads((source/'PREPARED.json').read_bytes())
        if sha(source/'eval_tokens.jsonl')!=meta['eval_tokens_sha256'] or sha(source/'EVAL_INDEX.json')!=meta['eval_index_sha256']:
            raise ValueError('FROZEN_REGRESSION_SOURCE_DRIFT')
        selection=set(json.loads((source/'EVAL_PROTOCOL.json').read_bytes())['ids'])
        rows=[r for r in read(source/'eval_tokens.jsonl') if r['id'] in selection]
        if len(rows)!=757:raise ValueError('ROW_SELECTION_DRIFT')
        with (a.out/'verifier_inputs.jsonl').open('w') as f:
            for i,r in enumerate(rows):
                record=dict(id=r['id'],position=i,ids=r['ids'],source_policy=r['source_policy'],
                    input_sha256=r['text_sha256'],oversized=len(r['ids'])>48700)
                f.write(json.dumps(record)+'\n')
        write(a.out/'CONTROL_FROZEN.json',dict(verifier_inputs_sha256=sha(a.out/'verifier_inputs.jsonl')))
        import shutil
        shutil.copyfile(source/'EVAL_INDEX.json',a.out/'EVAL_INDEX.json')
        shutil.copyfile(source/'EVAL_PROTOCOL.json',a.out/'EVAL_PROTOCOL.json')
        start=json.loads((a.out/'START.json').read_bytes())
        start.update(source_sha256=sha(ROOT/'scripts/v12_transfer.py'),controller_sha256=sha(Path(__file__)),
            labels_read=False,threshold=0,rows=757,phase='final_verifier',eval_index_sha256=meta['eval_index_sha256'],
            final_adapter=sha(trained/'adapter/adapter_model.safetensors'))
        write(a.out/'START.json',start)
        command=[sys.executable,str(ROOT/'scripts/v12_transfer.py'),'worker','--lab',str(a.lab),'--out',str(a.out),
            '--arm','new','--training',str(trained),'--deadline',str(a.deadline-60)]
        with (a.out/'worker.log').open('w',buffering=1) as f:
            active=subprocess.Popen(command,stdout=f,stderr=subprocess.STDOUT,start_new_session=True,cwd=ROOT)
            code=active.wait(timeout=max(1,a.deadline-30-time.time()))
        if code:raise ValueError('FINAL_REGRESSION_WORKER_EXIT:'+str(code))
        active=None;analyse(a,source)
        write(a.out/'DONE.json',dict(complete=True,seconds=time.monotonic()-started,results_sha256=sha(a.out/'RESULTS.json')))
    except Exception as e:
        write(a.out/'FAIL.json',dict(error=str(e),traceback=traceback.format_exc()));raise
    finally:
        if active is not None and active.poll() is None:
            os.killpg(active.pid,signal.SIGTERM)
            try:active.wait(timeout=30)
            except subprocess.TimeoutExpired:os.killpg(active.pid,signal.SIGKILL);active.wait()
        from scripts.v7_control import export
        export(a.out)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('lab','out'):p.add_argument('--'+k,type=Path,required=True)
    p.add_argument('--candidate-root',type=Path)
    p.add_argument('--deadline',type=float,required=True);run(p.parse_args())
