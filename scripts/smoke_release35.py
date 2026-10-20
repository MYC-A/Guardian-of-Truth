"""Finite production-format host-runtime integration smoke; no quality claims."""
import csv
import hashlib
import json
import os
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from scripts.judge35_submission import run,read
from scripts.lora35_support import write

lab=Path('/workspace/guardian-lab-20261018');out=lab/'v19-release35-20261020'
out.mkdir(exist_ok=False)
cfg=json.loads((ROOT/'JUDGE_CONFIG.json').read_bytes())
cfg.update(judge_stop_seconds=300,kill_seconds=360,watchdog_seconds=600)
cfg['lora35_verifier']['stop_seconds']=540
config=out/'config.json';write(config,cfg)
with (lab/'v10-full-profile-batch64-20261020/evaluation-v10/inputs.csv').open(newline='') as f:
    rows=list(csv.DictReader(f))[:6]
with (out/'inputs.csv').open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=['id','prompt','response']);w.writeheader();w.writerows([{k:r[k] for k in w.fieldnames} for r in rows])
started=time.time();run(ROOT,out/'inputs.csv',out/'predictions.csv',python=sys.executable,work=out/'work',config=config,started_wall=started)
receipt=json.loads((out/'work/LORA35_DONE.json').read_bytes())
if not receipt['applied']:raise ValueError('ADAPTER_NOT_APPLIED:'+str(receipt))
binding=json.loads((out/'work/verifier/ADAPTER_BINDING.json').read_bytes())
if len(binding)!=1 or not binding[0]['complete'] or binding[0]['covered_modules']!=100:raise ValueError('BINDING_NOT_COMPLETE')
values=read(out/'work/verifier/scores.jsonl')
if not any(r['admitted'] and r['exact'] for r in values):raise ValueError('NO_EXACT_ADMITTED_FINAL')
with (out/'predictions.csv').open(newline='') as f:pred=list(csv.DictReader(f))
if [r['id'] for r in rows]!=[r['id'] for r in pred]:raise ValueError('OUTPUT_ID_ORDER')
write(out/'DONE.json',dict(complete=True,rows=6,seconds=time.time()-started,adapter_applied=True,
    source_modules=100,admitted_exact=sum(r['admitted'] and r['exact'] for r in values),
    quality_measured=False,scope='6 production-format rows; host runtime; shortened clocks; not full private timing',
    source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()))
sys.stdout.flush();sys.stderr.flush();os._exit(0)
