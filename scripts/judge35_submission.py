"""Best-profile primary, then bounded 35B LoRA verification of its positives."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from scripts import judge_submission as primary
from scripts.lora35_support import write,reasoning_text,admit_review
from guardian_truth.judge.prompting import system_block

ADAPTER_SHA='4a44903c463d9244f2816ffd84d8f0bd8ba032a1340ca9b3716e6ae887101313'


def read(path):
    return [json.loads(x) for x in Path(path).read_bytes().split(b'\n') if x.strip()]


def apply_complete(before,hard,records):
    wanted={i for i,y in enumerate(before) if y}
    if len(records)!=len(wanted) or {r['position'] for r in records}!=wanted:
        raise ValueError('INCOMPLETE_VERIFIER_GLOBAL_BASELINE_FALLBACK')
    values={r['position']:r for r in records}
    for r in records:
        if r['admitted'] and (not r.get('exact') or not isinstance(r.get('score'),(int,float)) or not math.isfinite(r['score'])):
            raise ValueError('INEXACT_VERIFIER_GLOBAL_BASELINE_FALLBACK')
    return [int(bool(y) and (i in hard or not values[i]['admitted'] or values[i]['score']>0)) if y else 0
            for i,y in enumerate(before)]


def worker(a):
    from vllm import LLM,SamplingParams
    from vllm.lora.request import LoRARequest
    from scripts.judge_stage import engine_kwargs,answer_ids,answer_score,probe
    from scripts.lora35_support import bound_llm
    cfg=json.loads((a.work/'config.json').read_bytes());settings=cfg['lora35_verifier']
    adapter=ROOT/settings['adapter_dir']
    if hashlib.sha256((adapter/'adapter_model.safetensors').read_bytes()).hexdigest()!=ADAPTER_SHA:
        raise ValueError('ADAPTER_HASH_MISMATCH')
    cfg.update(gpu_memory_utilization=.85,dtype='bfloat16',engine_overrides=dict(enforce_eager=True,async_scheduling=False))
    kwargs,_=engine_kwargs(str(ROOT/cfg['model_dir']),cfg)
    request=LoRARequest('guardian-35b-v7',1,str(adapter));llm=None
    try:
        llm=bound_llm(LLM,request,a.work/'generation_audit.jsonl',adapter,100)(**kwargs)
        tok=llm.get_tokenizer();yes,no=answer_ids(tok)
        params=SamplingParams(temperature=1,top_p=1,max_tokens=1,logprobs=20,seed=0,allowed_token_ids=sorted(yes|no))
        if probe(llm,tok,params,yes,no)[0] is not True:raise ValueError('EXACT_PROBE_FAILED')
        gen=SamplingParams(temperature=0,max_tokens=192,seed=0,stop=['\nVerdict:'])
        rows=read(a.work/'inputs.jsonl');done=0
        with (a.work/'scores.jsonl').open('w',buffering=1) as f:
            for offset in range(0,len(rows),64):
                if time.time()>a.stop_at-20:raise TimeoutError('VERIFIER_BUDGET')
                batch=rows[offset:offset+64];records=[];inputs=[]
                for r in batch:
                    prompt=reasoning_text(r['text']);ids=tok.encode(prompt,add_special_tokens=False)
                    if tok.decode(ids,skip_special_tokens=False)!=prompt:raise ValueError('INPUT_TOKEN_ROUNDTRIP')
                    if hashlib.sha256(r['text'].encode()).hexdigest()!=r['model_input_sha256']:raise ValueError('PRIMARY_SOURCE_DRIFT')
                    record=dict(position=r['position'],admitted=False,exact=False,score=None,status='OVERSIZED')
                    if len(ids)<=48700:
                        inputs.append((len(records),ids,r['source_policy']))
                    records.append(record)
                outputs=llm.generate([dict(prompt_token_ids=x[1]) for x in inputs],gen,use_tqdm=False) if inputs else []
                if len(outputs)!=len(inputs):raise ValueError('REVIEW_COVERAGE')
                finals=[];positions=[]
                for (position,ids,policy),o in zip(inputs,outputs):
                    if list(o.prompt_token_ids)!=ids or not o.outputs:raise ValueError('REVIEW_INPUT_DRIFT')
                    sample=o.outputs[0];ok,status,support=admit_review(sample.text,policy,sample.finish_reason=='length')
                    records[position].update(admitted=ok,status=status,review=sample.text,source_support=support)
                    if ok:
                        final=tok.encode(tok.decode(ids,skip_special_tokens=False)+sample.text.strip()+'\nVerdict:',add_special_tokens=False)
                        if final[:len(ids)]!=ids or len(final)>=49152:raise ValueError('FINAL_TOKEN_BOUNDARY')
                        finals.append(dict(prompt_token_ids=final));positions.append(position)
                scores=llm.generate(finals,params,use_tqdm=False) if finals else []
                if len(scores)!=len(finals):raise ValueError('FINAL_COVERAGE')
                for i,o,p in zip(positions,scores,finals):
                    score,exact=answer_score(o,yes,no)
                    if not exact or score is None or not math.isfinite(score) or list(o.prompt_token_ids)!=p['prompt_token_ids']:
                        raise ValueError('INEXACT_FINAL')
                    records[i].update(score=score,exact=True)
                for r in records:f.write(json.dumps(r)+'\n')
                f.flush();os.fsync(f.fileno());done+=len(records)
                write(a.work/'PROGRESS.json',dict(done=done,total=len(rows),adapter_sha256=ADAPTER_SHA))
        write(a.work/'DONE.json',dict(complete=True,rows=done,adapter_sha256=ADAPTER_SHA,
            scores_sha256=hashlib.sha256((a.work/'scores.jsonl').read_bytes()).hexdigest()))
    finally:
        if llm is not None:llm.llm_engine.engine_core.shutdown()


def run(root,input_path,output,*,python=None,work=None,started_wall=None,config=None,watchdog=True):
    root=Path(root).resolve();cfg=primary.load_config(root,config);clock=primary.Clock(started_wall)
    if watchdog:primary.start_watchdog(clock,output,float(cfg['watchdog_seconds']))
    work=Path(work or tempfile.mkdtemp(prefix='guardian-35b-')).resolve();work.mkdir(parents=True,exist_ok=True)
    primary_work=work/'primary'
    # Original primary supervisor keeps producing durable baseline answers.
    primary.run(root,input_path,output,python=python,work=primary_work,started_wall=clock.started_wall,config=config,watchdog=False)
    receipt=dict(adapter_sha256=ADAPTER_SHA,applied=False,partial_native_training_included=False)
    process=None
    try:
        rows=primary.read_input(input_path);decisions=read(primary_work/'decisions.jsonl')
        if len(decisions)!=len(rows) or any(d['key']!=i or d['id']!=r['id'] for i,(d,r) in enumerate(zip(decisions,rows))):raise ValueError('BASELINE_ID_ORDER')
        before=[d['label'] for d in decisions];hard={i for i,d in enumerate(decisions) if d['hard']}
        pool=[i for i,y in enumerate(before) if y]
        if not pool:receipt['reason']='NO_POSITIVES';return 0
        overall,_,_,events=primary.read_scores(primary_work/'scores.jsonl',exact_only=True)
        final=primary.read_review_scores(primary_work/'scores.jsonl',isolate_duplicates=True)
        if set(overall)!=set(range(len(rows))) or set(final)!=set(overall) or events.get('failed') or 'done' not in events:
            raise ValueError('PRIMARY_NOT_FULL_EXACT_BASELINE_PRESERVED')
        if any(d['ranking']!='max_exact_overall_final' for d in decisions):raise ValueError('PRIMARY_MAX_FALLBACK')
        stop_at=clock.wall_at(float(cfg['lora35_verifier']['stop_seconds']))
        if time.time()>stop_at-120:raise TimeoutError('NO_VERIFIER_RESERVE_BASELINE_PRESERVED')
        spools=list(primary_work.glob('primary-inputs-*.jsonl'))
        if len(spools)!=1:raise ValueError('PRIMARY_SPOOL_AMBIGUOUS')
        stored=read(spools[0]);lookup={r['key']:r for r in stored}
        if len(stored)!=len(rows) or len(lookup)!=len(rows):raise ValueError('PRIMARY_SPOOL_COVERAGE')
        verifier=work/'verifier';verifier.mkdir(exist_ok=False)
        with (verifier/'inputs.jsonl').open('w') as f:
            for i in pool:
                r=lookup[i];text=r['text'];policy=system_block(text.split('<transcript>\n',1)[1].split('\n</transcript>',1)[0])
                if not policy:raise ValueError('MISSING_SOURCE_POLICY')
                f.write(json.dumps(dict(position=i,text=text,source_policy=policy,model_input_sha256=r['model_input_sha256']))+'\n')
        write(verifier/'config.json',cfg)
        bundled=root/'runtime/python/run_python.sh';binary=python or (str(bundled) if bundled.exists() else sys.executable)
        env=dict(os.environ,VLLM_ALLOW_INSECURE_SERIALIZATION='1',PYTHONUNBUFFERED='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
        if str(binary)==str(bundled):
            for k in ('PYTHONPATH','PYTHONHOME','LD_LIBRARY_PATH','LD_PRELOAD'):env.pop(k,None)
        command=[str(binary),str(root/'scripts/judge35_submission.py'),'--worker','--work',str(verifier),'--stop-at',str(stop_at)]
        with (verifier/'worker.log').open('w') as f:
            process=subprocess.Popen(command,stdout=f,stderr=subprocess.STDOUT,cwd=root,env=env,start_new_session=True)
            try:code=process.wait(timeout=max(1,stop_at-time.time()))
            except subprocess.TimeoutExpired:raise TimeoutError('VERIFIER_INCOMPLETE_BASELINE_PRESERVED')
        if code:raise ValueError('VERIFIER_EXIT_'+str(code))
        done=json.loads((verifier/'DONE.json').read_bytes())
        if not done['complete'] or hashlib.sha256((verifier/'scores.jsonl').read_bytes()).hexdigest()!=done['scores_sha256']:
            raise ValueError('VERIFIER_RECEIPT_DRIFT')
        after=apply_complete(before,hard,read(verifier/'scores.jsonl'))
        primary.write_labels(output,[r['id'] for r in rows],after)
        receipt.update(applied=True,rows=len(rows),candidates=len(pool),vetoed=sum(before)-sum(after),quota_refill=False)
    except Exception as error:
        receipt.update(reason=str(error));primary.log(clock,'lora35_baseline_preserved',reason=str(error))
    finally:
        if process is not None:primary.kill_group(process,grace=3)
        write(work/'LORA35_DONE.json',dict(receipt,seconds=clock.elapsed()))
    return 0


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--worker',action='store_true');p.add_argument('--work',type=Path,required=True);p.add_argument('--stop-at',type=float,required=True)
    args=p.parse_args();worker(args);sys.stdout.flush();sys.stderr.flush();os._exit(0)
