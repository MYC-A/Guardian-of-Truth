"""Unchanged R0 production evaluator on new frozen DEV/HOLDOUT, finite runtime."""
import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

LAB=Path('/workspace/guardian-lab-20261018')


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return [json.loads(x) for x in p.read_bytes().splitlines()]
def write(p,x):p.write_text(json.dumps(x,indent=2)+'\n')


def main():
    p=argparse.ArgumentParser();p.add_argument('--frozen',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();a.out.mkdir(exist_ok=False);start=time.time()
    # Freeze the unchanged R0 implementation from the completed E2 evidence;
    # new optional parser enforcement is scored separately from saved scores.
    root=LAB/'v3-20261019/e2-reference-v1/executed_code'
    config=LAB/'runs/regression_r1/judge_config.json'
    frozen=json.loads((a.frozen/'FROZEN.json').read_bytes());mapping=[];labels=[]
    with (a.out/'inputs.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['id','prompt','response']);writer.writeheader()
        for part in ('dev','holdout'):
            source=a.frozen/(part+'_inputs.jsonl');assert sha(source)==frozen['files'][source.name]
            gold=read(a.frozen/(part+'.jsonl'));rows=read(source);assert len(gold)==len(rows)
            for g,r in zip(gold,rows):
                assert g['id']==r['id'];position=len(mapping)
                mapping.append(dict(partition=part,id=r['id'],group=g['split_component']))
                labels.append(dict(position=position,id=r['id'],label=g['label']))
                writer.writerow(r)
    (a.out/'labels.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in labels))
    shutil.copy2(config,a.out/'judge_config.json')
    weights=json.loads((LAB/'models/qwen36-awq/VERIFIED.json').read_bytes())
    assert weights['revision']=='00fcea2d3bcf5389b518d4fc082e5590e0ba4844'
    n=len(mapping);record=dict(rows=n,input_mapping=mapping,status='EXPLORATORY_ONLY',weights=weights,
        source_root=str(root),source_sha256={str(p.relative_to(root)):sha(p) for p in root.rglob('*.py')},
        frozen_sha256=sha(a.frozen/'FROZEN.json'),config_sha256=sha(config),runner_sha256=sha(Path(__file__)),
        input_sha256=sha(a.out/'inputs.csv'),labels_separate=True,shape_gate_added_to_ranking=False)
    write(a.out/'START.json',record)
    env=dict(os.environ,PYTHONPATH=str(root/'src'),HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',
        VLLM_NO_USAGE_STATS='1',TOKENIZERS_PARALLELISM='false',PYTHON_DOTENV_DISABLED='1')
    cmd=[sys.executable,str(root/'scripts/eval_judge_valid.py'),'--input',str(a.out/'inputs.csv'),
         '--labels-file',str(a.out/'labels.jsonl'),'--config',str(config),'--model',str(LAB/'models/qwen36-awq'),
         '--rates','.30,.40,.50','--seconds','5400','--out',str(a.out/'run')]
    try:
        with (a.out/'eval.log').open('w',buffering=1) as f:r=subprocess.run(cmd,cwd=root,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=5550)
        assert r.returncode==0,('EVALUATOR_EXIT',r.returncode)
        with (a.out/'run/rows.csv').open(newline='') as f:rows=list(csv.DictReader(f))
        assert len(rows)==n
        for r,m in zip(rows,mapping):
            assert r['id']==m['id']
            assert all(math.isfinite(float(r[k])) for k in ('score','primary_score','final_score'))
            assert float(r['score'])==max(float(r['primary_score']),float(r['final_score']))
        summary=json.loads((a.out/'run/summary.json').read_bytes())
        assert summary['stage_exit']==0 and summary['review']['final_scored']==n and summary['ranking']=='max_exact_overall_final'
        record.update(complete=True,exact_primary=n,exact_final=n,wall_seconds=time.time()-start,
            output_sha256={p.name:sha(p) for p in (a.out/'run').iterdir() if p.is_file()})
        write(a.out/'DONE.json',record);print(json.dumps(dict(complete=True,rows=n,seconds=time.time()-start)),flush=True)
    except Exception as e:
        write(a.out/'FAIL.json',dict(complete=False,error_type=type(e).__name__,error=str(e),seconds=time.time()-start));raise


if __name__=='__main__':main()
