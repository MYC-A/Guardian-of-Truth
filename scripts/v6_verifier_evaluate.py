"""Paired native verifier evaluation; gold stays in the CPU analysis parent."""
import argparse
import json
import math
import os
from pathlib import Path
import signal
import statistics
import subprocess
import sys
import tarfile
import time
import traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src'),str(ROOT/'scripts')]
from scripts.v5_35b_common import BASE_REVISION,read,sha,verify_model,write
from scripts.v5_valid46_pipeline import bound_llm,metrics
from scripts.v6_verifier_data import OLD_ADAPTER_SHA
from guardian_truth.judge.decision import decide


def worker(a):
    data=json.loads((a.data/'DONE.json').read_bytes())
    if not data['complete'] or sha(a.data/'eval_tokens.jsonl')!=data['eval_tokens_sha256']:
        raise ValueError('EVAL_INPUT_DRIFT')
    rows=read(a.data/'eval_tokens.jsonl')
    if len(rows)!=1405 or any(set(r)!={'id','ids','tokens','text_sha256'} for r in rows):
        raise ValueError('EVAL_SCHEMA_OR_GOLD_LEAK')
    adapter=None
    if a.arm!='base':
        source=a.old if a.arm=='old' else a.new
        meta=json.loads((source/'TRAINED.json').read_bytes());adapter=source/'adapter'
        if not meta['complete'] or meta['base_revision']!=BASE_REVISION or sha(adapter/'adapter_model.safetensors')!=meta['adapter_sha256']:
            raise ValueError('EVAL_ADAPTER_DRIFT')
        if a.arm=='old' and meta['adapter_sha256']!=OLD_ADAPTER_SHA:raise ValueError('OLD_ADAPTER_DRIFT')
        if a.arm=='new' and (meta['source_adapter_sha256']!=OLD_ADAPTER_SHA or meta['optimizer_updates']<=0):raise ValueError('WARM_START_NOT_PROVEN')
    verify_model(a.model,a.manifest)
    from vllm import LLM,SamplingParams
    from vllm.lora.request import LoRARequest
    from scripts.judge_stage import answer_ids,answer_score,engine_kwargs,probe
    request=None if adapter is None else LoRARequest('v6-'+a.arm,1,str(adapter.resolve()))
    config=json.loads((ROOT/'submission/JUDGE_OPEN_REVIEW40.json').read_bytes())
    config.update(max_model_len=49152,gpu_memory_utilization=.85,max_num_seqs=16,
        max_num_batched_tokens=8192,dtype='bfloat16',multimodal=True,enable_prefix_caching=True,
        engine_overrides=dict(enforce_eager=True,async_scheduling=False))
    kwargs,dropped=engine_kwargs(str(a.model),config)
    llm=bound_llm(LLM,request,a.out/'generation_audit.jsonl',binding_adapter=adapter)(**kwargs)
    yes,no=answer_ids(llm.get_tokenizer())
    if sorted(yes)!=data['answer_ids']['yes'] or sorted(no)!=data['answer_ids']['no']:raise ValueError('ANSWER_TOKEN_DRIFT')
    params=SamplingParams(temperature=1.0,top_p=1.0,max_tokens=1,logprobs=20,seed=0,allowed_token_ids=sorted(yes|no))
    exact_mode,info=probe(llm,llm.get_tokenizer(),params,yes,no)
    if exact_mode is not True:raise ValueError('EXACT_SCORING_PROBE_FAILED:'+str(exact_mode))
    write(a.out/'PROBE.json',dict(exact_mode=exact_mode,info=info))
    started=time.monotonic();done=0
    with (a.out/'scores.jsonl').open('w',buffering=1) as f:
        for offset in range(0,len(rows),16):
            batch=rows[offset:offset+16]
            outputs=llm.generate([dict(prompt_token_ids=r['ids']) for r in batch],params,use_tqdm=False)
            if len(outputs)!=len(batch):raise ValueError('OUTPUT_COUNT')
            for row,output in zip(batch,outputs):
                value,exact=answer_score(output,yes,no)
                if list(output.prompt_token_ids)!=row['ids'] or not exact or value is None or not math.isfinite(value):raise ValueError('INEXACT_OR_TOKEN_DRIFT:'+row['id'])
                f.write(json.dumps(dict(id=row['id'],arm=a.arm,score=value,exact=True,tokens=row['tokens'],text_sha256=row['text_sha256']))+'\n')
            done+=len(batch)
            write(a.out/'PROGRESS.json',dict(rows_done=done,rows_total=len(rows),seconds=time.monotonic()-started,arm=a.arm))
    repeated=[r for r in rows if ':valid46:' in r['id']]
    if len(repeated)!=46:raise ValueError('VALID46_REPEAT_IDENTITY')
    with (a.out/'repeat_scores.jsonl').open('w',buffering=1) as f:
        for repeat in (1,2):
            for offset in range(0,len(repeated),16):
                batch=repeated[offset:offset+16]
                outputs=llm.generate([dict(prompt_token_ids=r['ids']) for r in batch],params,use_tqdm=False)
                if len(outputs)!=len(batch):raise ValueError('REPEAT_OUTPUT_COUNT')
                for row,output in zip(batch,outputs):
                    value,exact=answer_score(output,yes,no)
                    if list(output.prompt_token_ids)!=row['ids'] or not exact or value is None or not math.isfinite(value):raise ValueError('REPEAT_INEXACT_OR_TOKEN_DRIFT')
                    f.write(json.dumps(dict(id=row['id'],arm=a.arm,repeat=repeat,score=value,exact=True))+'\n')
    write(a.out/'DONE.json',dict(complete=True,arm=a.arm,rows=done,all_exact=True,
        input_sha256=data['eval_tokens_sha256'],scores_sha256=sha(a.out/'scores.jsonl'),
        adapter_sha256=sha(adapter/'adapter_model.safetensors') if adapter else None,
        seconds=time.monotonic()-started,dropped_engine_kwargs=dropped,
        repeat_scores_sha256=sha(a.out/'repeat_scores.jsonl'),valid46_measurements=3,
        apc=True,result_cache=False,scope='whole-turn verifier score; not full ZIP pipeline'))
    sys.stdout.flush();sys.stderr.flush();os._exit(0)


def analyse(a):
    prepared=json.loads((a.data/'DONE.json').read_bytes())
    if sha(a.data/'EVAL_INDEX.json')!=prepared['eval_index_sha256']:raise ValueError('GOLD_INDEX_DRIFT')
    index=json.loads((a.data/'EVAL_INDEX.json').read_bytes())['rows'];gold={r['id']:r['label'] for r in index}
    arms={}
    for arm in ('base','old','new'):
        folder=a.out/arm;done=json.loads((folder/'DONE.json').read_bytes())
        if (not done['complete'] or done['rows']!=1405 or done['input_sha256']!=prepared['eval_tokens_sha256']
                or sha(folder/'scores.jsonl')!=done['scores_sha256']):raise ValueError('INCOMPLETE_ARM:'+arm)
        values=read(folder/'scores.jsonl')
        if len(values)!=1405 or {r['id'] for r in values}!=set(gold) or any(not r['exact'] for r in values):raise ValueError('SCORED_ID_OR_EXACT_DRIFT')
        if arm!='base':
            binding=json.loads((folder/'ADAPTER_BINDING.json').read_bytes())
            if len(binding)!=1 or not binding[0]['complete'] or binding[0]['covered_modules']!=50:raise ValueError('INCOMPLETE_GPU_BINDING:'+arm)
        arms[arm]={r['id']:r for r in values}
    # Historical plain-base overall scores are valid; earlier shared-expert bug affected adapters only.
    baseline_dir=a.lab/'v5-35b-20261019/finish-v6/paired-native'
    receipt=json.loads((baseline_dir/'WORKER_DONE.json').read_bytes())
    original_prepared=json.loads((a.lab/'v5-35b-20261019/eval-inputs-v1/PREPARED.json').read_bytes())
    if receipt['tokens_sha256']!=original_prepared['tokens_sha256']:raise ValueError('ORIGINAL_BASE_TOKEN_SOURCE_DRIFT')
    if sha(baseline_dir/'scores.jsonl')!=receipt['scores_sha256']:raise ValueError('ORIGINAL_BASE_SCORE_DRIFT')
    baseline={r['id']:r for r in read(baseline_dir/'scores.jsonl') if r['arm']=='base'}
    if set(baseline)!=set(gold) or any(not r['exact'] or not math.isfinite(r['score']) for r in baseline.values()):raise ValueError('ORIGINAL_BASE_COVERAGE')
    result=dict(complete=True,status='EXPLORATORY_ONLY_HUMAN_UNVERIFIED',independent_validation=False,
        private_improvement_measured=False,production_promoted=False,threshold=0,threshold_search=False,
        quota_refill=False,input_sha256=prepared['eval_tokens_sha256'],cohorts={},stability={},
        historical_original_base_scores_sha256=receipt['scores_sha256'],
        original_pool_scope='historical classifier-only overall with hard; not best-ZIP open-review MAX')
    for arm in arms:
        repeats=read(a.out/arm/'repeat_scores.jsonl')
        receipt_arm=json.loads((a.out/arm/'DONE.json').read_bytes())
        if sha(a.out/arm/'repeat_scores.jsonl')!=receipt_arm['repeat_scores_sha256'] or len(repeats)!=92:
            raise ValueError('REPEAT_RECEIPT_DRIFT')
        deltas=[r['score']-arms[arm][r['id']]['score'] for r in repeats]
        result['stability'][arm]=dict(measurements=3,rows=46,apc=True,
            independent_tasks=False,sd_differences_over_sqrt2=statistics.stdev(deltas)/math.sqrt(2),
            max_abs_score_delta=max(abs(x) for x in deltas),
            changed_score0_decisions=sum((r['score']>0)!=(arms[arm][r['id']]['score']>0) for r in repeats),
            comparisons=92,absolute_stability_of_private_data_confirmed=False)
    for cohort in ('real191','dev520','valid46','seen397','dev152','hold336'):
        rows=[r for r in index if cohort in r['cohorts']]
        if not rows:continue
        hard={i for i,r in enumerate(rows) if r['hard']}
        baseline_scores={i:baseline[r['id']]['score'] for i,r in enumerate(rows)}
        p40=decide(len(rows),hard,baseline_scores,.4)
        result['cohorts'][cohort]=dict(rows=len(rows),original_overall_pool40=metrics(rows,gold,p40),arms={})
        decisions={arm:[int(i in hard or arms[arm][r['id']]['score']>0) for i,r in enumerate(rows)] for arm in arms}
        for arm,labels in decisions.items():
            ref=decisions['base'];filtered=[int(y and z) for y,z in zip(p40,labels)]
            result['cohorts'][cohort]['arms'][arm]=dict(
                raw_score0=metrics(rows,gold,[int(arms[arm][r['id']]['score']>0) for r in rows]),
                hard_protected_score0=metrics(rows,gold,labels),
                removed_fp_vs_base_verifier=sum(z and not y and gold[r['id']]==0 for r,y,z in zip(rows,labels,ref)),
                lost_tp_vs_base_verifier=sum(z and not y and gold[r['id']]==1 for r,y,z in zip(rows,labels,ref)),
                added_fp_vs_base_verifier=sum(y and not z and gold[r['id']]==0 for r,y,z in zip(rows,labels,ref)),
                original_pool40_after_verifier=metrics(rows,gold,filtered),
                pool40_removed_fp=sum(z and not y and gold[r['id']]==0 for r,y,z in zip(rows,filtered,p40)),
                pool40_lost_tp=sum(z and not y and gold[r['id']]==1 for r,y,z in zip(rows,filtered,p40)))
    # Keep the actual best-pipeline valid46 pool separately, with no substitution by old overall.
    best=read(a.lab/'v5-35b-20261019/pipeline-valid46-v4/base/work/decisions.jsonl')
    hard={r['key'] for r in best if r['hard']};scores={r['key']:r['ranked_by'] for r in best}
    p70=decide(46,hard,scores,.7)
    lookup={r['original_id']:r for r in index if 'valid46' in r['cohorts']}
    best_rows=[dict(id=lookup[r['id']]['id']) for r in best]
    result['best_pipeline_valid46_pool70']=dict(before=metrics(best_rows,gold,p70),arms={})
    for arm in arms:
        labels=[int(y and (b['key'] in hard or arms[arm][r['id']]['score']>0)) for b,r,y in zip(best,best_rows,p70)]
        result['best_pipeline_valid46_pool70']['arms'][arm]=dict(metrics=metrics(best_rows,gold,labels),
            removed_fp=sum(z and not y and gold[r['id']]==0 for r,y,z in zip(best_rows,labels,p70)),
            lost_tp=sum(z and not y and gold[r['id']]==1 for r,y,z in zip(best_rows,labels,p70)))
    tests={}
    for c in ('real191','dev520'):
        t=result['cohorts'][c]['arms'];b=t['base']['hard_protected_score0'];n=t['new']['hard_protected_score0']
        tests[c]=n['fp']<b['fp'] and t['new']['lost_tp_vs_base_verifier']==0
    tests['valid46_no_new_tp_loss']=result['cohorts']['valid46']['arms']['new']['lost_tp_vs_base_verifier']==0
    result['offline_gate']=dict(tests=tests,passed=all(tests.values()),promotion_approved=False)
    write(a.out/'RESULTS.json',result)
    return result


def parent(a):
    a.out.mkdir(exist_ok=False);started=time.monotonic();previous=a.lab/'v5-35b-20261019'
    active=None
    def stop(_sig,_frame):
        if active is not None and active.poll() is None:
            os.killpg(active.pid,signal.SIGTERM)
            try:active.wait(timeout=90)
            except subprocess.TimeoutExpired:os.killpg(active.pid,signal.SIGKILL);active.wait()
        raise RuntimeError('SUPERVISED_EVALUATION_STOP_REQUESTED')
    signal.signal(signal.SIGTERM,stop)
    write(a.out/'START.json',dict(complete=False,source_sha256=sha(Path(__file__)),quality_retries=0,
        arm_order=['base','old','new'],total_scoring_timeout_seconds=5400,gold_in_worker=False))
    try:
        deadline=time.monotonic()+8200
        while not (a.new/'TRAINED.json').exists():
            if (a.new/'FAIL.json').exists() or (a.new.parent/'FAIL.json').exists():raise RuntimeError('TRAINING_FAILED')
            if time.monotonic()>deadline:raise TimeoutError('TRAINING_WAIT_LIMIT')
            time.sleep(20)
        for _ in range(90):
            if subprocess.check_output(['nvidia-smi','--query-gpu=memory.used','--format=csv,noheader,nounits'],text=True).strip()=='0':break
            time.sleep(1)
        else:raise RuntimeError('GPU_NOT_RELEASED')
        scoring_started=time.monotonic()
        for arm in ('base','old','new'):
            remaining=5400-(time.monotonic()-scoring_started)
            if remaining<=0:raise TimeoutError('TOTAL_SCORING_BUDGET')
            folder=a.out/arm;folder.mkdir()
            command=[sys.executable,str(Path(__file__).resolve()),'worker','--lab',str(a.lab),
                '--data',str(a.data),'--new',str(a.new),'--out',str(folder),'--arm',arm,
                '--old',str(previous/'train-recovered-v1'),'--model',str(a.lab/'models/qwen36-awq'),
                '--manifest',str(previous/'BASE_MODEL_MANIFEST.json')]
            with (folder/'worker.log').open('w',buffering=1) as log:
                proc=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,cwd=ROOT,
                    env=dict(os.environ,VLLM_ALLOW_INSECURE_SERIALIZATION='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',
                        PYTHON_DOTENV_DISABLED='1',PYTHONUNBUFFERED='1'))
                active=proc
                try:code=proc.wait(timeout=remaining)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid,signal.SIGTERM)
                    try:proc.wait(timeout=90)
                    except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
                    raise
                active=None
            if code:raise RuntimeError('NATIVE_ARM_FAILED:'+arm+':'+str(code))
        result=analyse(a)
        write(a.out/'DONE.json',dict(complete=True,seconds=time.monotonic()-started,
            results_sha256=sha(a.out/'RESULTS.json'),gate_passed=result['offline_gate']['passed']))
    except Exception as e:
        write(a.out/'FAIL.json',dict(complete=False,error=str(e),traceback=traceback.format_exc(),seconds=time.monotonic()-started));raise
    finally:
        archive=a.out.parent/(a.out.name+'-export.tar.gz')
        with tarfile.open(archive,'w:gz',compresslevel=3) as tar:tar.add(a.out,arcname='evaluation')
        write(a.out.parent/(a.out.name+'-export.INDEX.json'),dict(name=archive.name,bytes=archive.stat().st_size,
            sha256=sha(archive),evaluation_complete=(a.out/'DONE.json').exists()))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['run','worker','analyse'])
    for n in ('lab','data','new','out'):p.add_argument('--'+n,type=Path,required=True)
    for n in ('old','model','manifest'):p.add_argument('--'+n,type=Path)
    p.add_argument('--arm',choices=['base','old','new'])
    a=p.parse_args()
    if a.mode=='worker':worker(a)
    elif a.mode=='analyse':analyse(a)
    else:parent(a)
