"""Finite operator GPU check; waits for own frozen reference to release the GPU."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def write(p,x):p.write_text(json.dumps(x,indent=2)+'\n')


def main():
    p=argparse.ArgumentParser();p.add_argument('--lab',type=Path,required=True);p.add_argument('--code',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    a.out.mkdir(exist_ok=False);start=time.monotonic();csv.field_size_limit(2**31-1)
    write(a.out/'START.json',dict(code=str(a.code),wait_for='own frozen reference-v1 GPU release',
        runtime='host lab venv; archive runtime verified separately',seconds_limit=1790,quality_set='previously explored valid46',
        source_sha256={str(f.relative_to(a.code)):hashlib.sha256(f.read_bytes()).hexdigest() for f in a.code.rglob('*.py') if 'model' not in f.relative_to(a.code).parts}))
    try:
        while True:
            ready=(a.lab/'v4-20261019/reference-v1/DONE.json').exists()
            failed=(a.lab/'v4-20261019/finish-v1/FAIL.json').exists()
            used=subprocess.check_output(['nvidia-smi','--query-gpu=memory.used','--format=csv,noheader,nounits'],text=True).strip()
            if (ready or failed) and used=='0':break
            if time.monotonic()-start>7200:raise TimeoutError('OWN_REFERENCE_WAIT_LIMIT')
            time.sleep(10)
        with (a.lab/'runs/valid46_r1/rows.csv').open(newline='') as f:valid={r['id'] for r in csv.DictReader(f)}
        with (a.lab/'data/guardian-judge-eval-data-v1/regression_seen/inputs.csv').open(newline='') as f:rows=[r for r in csv.DictReader(f) if r['id'] in valid]
        gold={r['id']:r['label'] for r in [json.loads(l) for l in (a.lab/'data/guardian-judge-eval-data-v1/regression_seen/labels.jsonl').read_bytes().splitlines()]}
        assert len(rows)==len(valid)==46
        with (a.out/'inputs.csv').open('w',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=['id','prompt','response']);writer.writeheader();writer.writerows(rows)
        env=dict(os.environ,GUARDIAN_STARTED_AT=repr(time.time()),HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTHON_DOTENV_DISABLED='1')
        timer=time.monotonic()
        with (a.out/'predict.log').open('w',buffering=1) as log:
            result=subprocess.run([sys.executable,str(a.code/'scripts/judge_blend_submission.py'),'--input',str(a.out/'inputs.csv'),
                '--output',str(a.out/'predictions.csv'),'--work-dir',str(a.out/'work')],cwd=a.code,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=1790)
        seconds=time.monotonic()-timer;assert result.returncode==0,('PREDICT_EXIT',result.returncode)
        done=json.loads((a.out/'work/BLEND_DONE.json').read_bytes())
        assert done['ranking']=='rank_50_50' and done['primary_exact_rows']==done['secondary_exact_rows']==46,done
        with (a.out/'predictions.csv').open(newline='') as f:output=list(csv.DictReader(f))
        assert [r['id'] for r in output]==[r['id'] for r in rows]
        metrics={};decisions=[json.loads(l) for l in (a.out/'work/decisions.jsonl').read_bytes().splitlines()]
        sys.path[:0]=[str(a.code),str(a.code/'src')]
        from guardian_truth.judge.decision import decide
        hard={i for i,r in enumerate(decisions) if r['hard']};base={i:r['primary_score'] for i,r in enumerate(decisions)}
        arms={'blend':[int(r['label']) for r in output],'same_run_primary_fixes':decide(46,hard,base,.4)}
        for arm,pred in arms.items():
            assert all(x in (0,1) for x in pred)
            tp=sum(gold[r['id']]==1 and y==1 for r,y in zip(rows,pred));fp=sum(gold[r['id']]==0 and y==1 for r,y in zip(rows,pred))
            fn=sum(gold[r['id']]==1 and y==0 for r,y in zip(rows,pred));tn=46-tp-fp-fn
            metrics[arm]=dict(tp=tp,fp=fp,fn=fn,tn=tn,f1=2*tp/(2*tp+fp+fn))
        write(a.out/'DONE.json',dict(complete=True,quality_scope='valid46 regression only',metrics=metrics,
            seconds=seconds,pipeline=done,private_test_time_proven=False,archive_runtime_executed=False,
            output_sha256=hashlib.sha256((a.out/'predictions.csv').read_bytes()).hexdigest()))
    except Exception as error:
        write(a.out/'FAIL.json',dict(complete=False,error_type=type(error).__name__,error=str(error),seconds=time.monotonic()-start));raise


if __name__=='__main__':main()
