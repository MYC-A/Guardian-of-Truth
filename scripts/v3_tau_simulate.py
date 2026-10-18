"""Bounded official tau2 trajectories, all LLM traffic restricted to localhost."""
import argparse
import concurrent.futures
import hashlib
import json
import os
import time
import urllib.request
from pathlib import Path

os.environ['PYTHON_DOTENV_DISABLED']='1'
os.environ['TAU2_DATA_DIR']='/workspace/guardian-lab-20261018/v3-20261019/tau2-source/data'

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--config-name',required=True);parser.add_argument('--per-domain',type=int,default=3)
    args=parser.parse_args();args.out.mkdir(exist_ok=False)
    from loguru import logger
    logger.remove();logger.add(lambda msg: print(msg,end='',flush=True),level='ERROR')
    from tau2.run import TextRunConfig,run_single_task,get_tasks
    from tau2.evaluator.evaluator import EvaluationType
    from tau2.runner.build import build_environment
    from tau2.utils import llm_utils
    # Refuse any omitted/default remote model, including an unexpected evaluator.
    original=llm_utils.completion
    def local_completion(*pos,**kw):
        assert not pos and kw.get('model')=='openai/guardian-local', 'NONLOCAL_MODEL_BLOCKED'
        assert kw.get('api_base')=='http://127.0.0.1:18140/v1', 'NONLOCAL_ENDPOINT_BLOCKED'
        return original(**kw)
    llm_utils.completion=local_completion
    for attempt in range(120):
        try:
            with urllib.request.urlopen('http://127.0.0.1:18140/health',timeout=3) as r: assert r.status==200
            break
        except Exception:
            if attempt==119: raise
            time.sleep(2)
    jobs=[];catalog={}
    for domain in ('airline','retail','telecom'):
        env=build_environment(domain)
        catalog[domain]=dict(policy=env.get_policy(),tools=[t.openai_schema for t in env.get_tools()])
        tasks=get_tasks(domain)
        tasks.sort(key=lambda task:hashlib.sha256(('guardian-v3:'+domain+':'+task.id).encode()).hexdigest())
        # Whole task IDs across all models/seeds remain in one future split group.
        for task in tasks[:args.per_domain]:
            for seed in (20261019,20261020): jobs.append((domain,task,seed))
    (args.out/'CATALOG.json').write_text(json.dumps(catalog,indent=2))
    manifest=dict(config_name=args.config_name,jobs=[dict(domain=d,task_id=t.id,seed=s) for d,t,s in jobs],
                  evaluation='ENV_ONLY_NOT_TURN_LABELS',remote_llm_calls_allowed=False,
                  script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (args.out/'START.json').write_text(json.dumps(manifest,indent=2));started=time.time()
    shared=dict(api_base='http://127.0.0.1:18140/v1',api_key='local-only',max_tokens=512,
                temperature=.4,timeout=90,num_retries=0,extra_body={'chat_template_kwargs':{'enable_thinking':False}})
    def run(job):
        domain,task,seed=job;key=hashlib.sha256((domain+task.id+str(seed)).encode()).hexdigest()[:16]
        record=dict(domain=domain,task_id=task.id,seed=seed,config_name=args.config_name)
        try:
            config=TextRunConfig(domain=domain,llm_agent='openai/guardian-local',llm_user='openai/guardian-local',
                llm_args_agent=dict(shared,seed=seed),llm_args_user=dict(shared,seed=seed+1),
                max_steps=60,max_errors=3,timeout=300,max_retries=0,auto_review=False,
                verbose_logs=True,log_level='ERROR')
            sim=run_single_task(config,task,seed=seed,evaluation_type=EvaluationType.ENV,
                                save_dir=args.out/key,verbose_logs=True,auto_review=False)
            record.update(complete=True,simulation=sim.model_dump(mode='json'),task=task.model_dump(mode='json'))
        except Exception as exc:
            record.update(complete=False,error_type=type(exc).__name__,error=str(exc)[:1500])
        (args.out/(key+'.json')).write_text(json.dumps(record,indent=2))
        print(json.dumps({k:v for k,v in record.items() if k not in ('simulation','task')}),flush=True)
        return record
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool: records=list(pool.map(run,jobs))
    done=dict(completed=sum(r['complete'] for r in records),attempted=len(records),seconds=time.time()-started,
              trajectory_reward_is_not_turn_label=True)
    (args.out/'DONE.json').write_text(json.dumps(done,indent=2));print(json.dumps(done),flush=True)
    if not done['completed']:raise SystemExit(1)

if __name__=='__main__':main()
