import hashlib,json,os,pathlib,subprocess,sys,time
root=pathlib.Path('/workspace/guardian-lab-20261018/blend-20261019/code')
sys.path[:0]=[str(root),str(root/'src')]
from scripts import judge_submission as p
from guardian_truth.judge.mechanical import analyze
from guardian_truth.judge.ensemble import read_secondary
out=root.parent/'aux-dev520-budget-v1';out.mkdir(exist_ok=False)
started=time.time();clock=p.Clock(repr(started));cfg=p.load_config(root,None);e=cfg['ensemble']
assert subprocess.check_output(['nvidia-smi','--query-gpu=memory.used','--format=csv,noheader,nounits'],text=True).strip()=='0'
rows=p.read_input(pathlib.Path('/workspace/guardian-lab-20261018/data/guardian-judge-eval-data-v1/compli_dev/inputs.csv'))
assert len(rows)==520
sec=dict(cfg,model_dir=e['model_dir'],review_mode='off',review_content='state_notes',review_ranking='complete',max_model_len=98304,gpu_memory_utilization=.85,dtype='bfloat16',multimodal=False,max_num_seqs=16,max_num_batched_tokens=16384,engine_overrides={'enforce_eager':True},questions=['overall'],hint_modes=['off'],aggregate='primary')
sec.pop('ensemble',None)
findings=[analyze(r['prompt'],r['response'],False,bounded_turn_shape=True) for r in rows]
command,env,scores,_=p.prepare_stage(root,sec,rows,findings,clock,out,sys.executable)
command[1]=str(root/'scripts/judge_lora_stage.py');stop=clock.wall_at(240)
command[command.index('--stop-at')+1]=repr(stop)
command+=['--adapter',str(root/e['adapter_dir'])]
env.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTHON_DOTENV_DISABLED='1')
(out/'START.json').write_text(json.dumps(dict(rows=520,budget=240,source_commit='2365fdc3a9c0b2f294fada1eb7f78a798a1fb318',purpose='auxiliary coverage and timing only; no labels',host_venv=True),indent=2)+'\n')
proc=None
try:
 with (out/'stage.log').open('w') as log:
  proc=subprocess.Popen(command,cwd=out,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
  while proc.poll() is None and time.time()<stop:time.sleep(.2)
  exit_code=proc.poll();deadline=exit_code is None
finally:gone=p.kill_group(proc,grace=3) if proc else True
exact=read_secondary(scores,520)
result=dict(complete=True,rows=520,exact_rows=len(exact),seconds=time.time()-started,budget_seconds=240,deadline=deadline,exit_code=exit_code,group_gone=gone,would_blend_if_primary_complete=len(exact)==520,private_test_time_proven=False)
(out/'DONE.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)
