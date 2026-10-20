"""Finite full-profile transfer comparison; all quality outputs freeze before gold."""
import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import traceback
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src'),str(ROOT/'scripts')]
from scripts.v5_35b_common import read,sha,write,verify_model
from scripts.v5_valid46_pipeline import pipeline_config,bound_llm,metrics
from scripts.v8_quote_contract import admit_review

INPUT_SHA='83bb8bb7287d12c8fc15156b69025d5929a26df0f13afe7913448ca404b97034'
ADAPTER_SHA='4a44903c463d9244f2816ffd84d8f0bd8ba032a1340ca9b3716e6ae887101313'


def filtered(before,hard,values):
    """Unknown evidence preserves positives; no refilling after a veto."""
    return [int(bool(y) and (i in hard or not values[i]['admitted'] or values[i]['score']>0))
            if y else 0 for i,y in enumerate(before)]


def prepare_verifier(a):
    from transformers import AutoTokenizer
    from scripts.v7_prepare import reasoning_text
    from guardian_truth.judge.prompting import system_block
    from scripts import judge_submission as primary
    from guardian_truth.judge.decision import decide
    csv.field_size_limit(2**31-1)
    with (a.out/'predictions.csv').open(encoding='utf-8',newline='') as f:pred=list(csv.DictReader(f))
    decisions=read(a.out/'work/decisions.jsonl')
    overall,missing,inexact,events=primary.read_scores(a.out/'work/scores.jsonl',exact_only=True)
    final=primary.read_review_scores(a.out/'work/scores.jsonl',isolate_duplicates=True)
    if set(overall)!=set(range(1893)) or set(final)!=set(overall) or missing or inexact or 'done' not in events:
        raise ValueError('FULL_EXACT_CONTROL_COVERAGE_REQUIRED')
    if len(pred)!=1893 or len(decisions)!=1893 or [r['id'] for r in pred]!=[r['id'] for r in decisions]:
        raise ValueError('BASELINE_ORDER')
    if any(r['ranking']!='max_exact_overall_final' for r in decisions):raise ValueError('BASELINE_FALLBACK')
    hard={i for i,r in enumerate(decisions) if r['hard']}
    if decide(1893,hard,{i:max(overall[i],final[i]) for i in overall},.4)!=[int(r['label']) for r in pred]:
        raise ValueError('BASELINE_MAX_REPLAY')
    audit=read(a.out/'generation_audit.jsonl')
    if not audit or any(r['adapter_applied'] for r in audit):raise ValueError('CONTROL_ADAPTER_DRIFT')
    spools=list((a.out/'work').glob('primary-inputs-*.jsonl'))
    if len(spools)!=1:raise ValueError('PRIMARY_SPOOL_AMBIGUOUS')
    records=read(spools[0]);lookup={r['key']:r for r in records}
    if len(lookup)!=1893:raise ValueError('PRIMARY_SPOOL_COVERAGE')
    tok=AutoTokenizer.from_pretrained(a.lab/'models/qwen36-awq',local_files_only=True)
    rows=[]
    for i,p in enumerate(pred):
        if not int(p['label']):continue
        r=lookup[i];text=r['text']
        if hashlib.sha256(text.encode()).hexdigest()!=r['model_input_sha256']:raise ValueError('PRIMARY_TEXT_HASH')
        policy=system_block(text.split('<transcript>\n',1)[1].split('\n</transcript>',1)[0])
        if not policy:raise ValueError('EMPTY_POLICY')
        prompt=reasoning_text(text);ids=tok.encode(prompt,add_special_tokens=False)
        if tok.decode(ids,skip_special_tokens=False)!=prompt:raise ValueError('VERIFIER_ROUNDTRIP')
        rows.append(dict(id=p['id'],position=i,ids=ids,source_policy=policy,
            input_sha256=hashlib.sha256(prompt.encode()).hexdigest(),oversized=len(ids)>48700,
            primary_trimmed=r['trimmed'],policy_trimmed=r['policy_trimmed']))
    with (a.out/'verifier_inputs.jsonl').open('w') as f:
        for r in rows:f.write(json.dumps(r)+'\n')
    write(a.out/'CONTROL_FROZEN.json',dict(complete=True,rows=1893,candidates=len(rows),
        predictions_sha256=sha(a.out/'predictions.csv'),scores_sha256=sha(a.out/'work/scores.jsonl'),
        verifier_inputs_sha256=sha(a.out/'verifier_inputs.jsonl'),primary_spool_sha256=sha(spools[0]),labels_read=False))


def worker(a):
    from vllm import LLM,SamplingParams
    from vllm.lora.request import LoRARequest
    from scripts.judge_stage import engine_kwargs,answer_ids,answer_score,probe
    a.worker_out=a.out/a.arm;a.worker_out.mkdir(exist_ok=False)
    if sha(Path(__file__))!=json.loads((a.out/'START.json').read_bytes())['source_sha256']:raise ValueError('EVALUATOR_CODE_DRIFT')
    receipt=json.loads((a.out/'CONTROL_FROZEN.json').read_bytes())
    if sha(a.out/'verifier_inputs.jsonl')!=receipt['verifier_inputs_sha256']:raise ValueError('INPUT_DRIFT')
    training=getattr(a,'training',None);expected_sha=ADAPTER_SHA
    adapter=a.lab/'v7-workflow-20261020/training-v2/layers16/adapter' if a.arm=='new' else None
    if training is not None:
        if a.arm!='new':raise ValueError('TRAINING_OVERRIDE_ONLY_FOR_NEW_ARM')
        trained=json.loads((training/'TRAINED.json').read_bytes())
        from scripts.v5_35b_common import BASE_REVISION
        if (not trained['complete'] or not trained['epoch_complete'] or trained['base_revision']!=BASE_REVISION or
                trained.get('recipe')!='V15_NATIVE_RATIONALE_V1' or trained['rows_done']!=trained['rows_total']):raise ValueError('INCOMPLETE_OR_WRONG_NATIVE_TRAINING')
        adapter=training/'adapter';expected_sha=trained['adapter_sha256']
    if adapter is not None and sha(adapter/'adapter_model.safetensors')!=expected_sha:raise ValueError('ADAPTER_DRIFT')
    request=LoRARequest('v12-frozen',1,str(adapter)) if adapter else None
    cfg=pipeline_config(a.lab/'models/qwen36-awq');cfg.update(gpu_memory_utilization=.85,dtype='bfloat16')
    kwargs,_=engine_kwargs(str(a.lab/'models/qwen36-awq'),cfg)
    llm=None
    try:
        llm=bound_llm(LLM,request,a.worker_out/'generation_audit.jsonl',binding_adapter=adapter,expected_source_modules=100)(**kwargs)
        tok=llm.get_tokenizer();yes,no=answer_ids(tok)
        params=SamplingParams(temperature=1,top_p=1,max_tokens=1,logprobs=20,seed=0,allowed_token_ids=sorted(yes|no))
        exact,info=probe(llm,tok,params,yes,no)
        if exact is not True:raise ValueError('EXACT_PROBE')
        write(a.worker_out/'PROBE.json',dict(exact=exact,info=info))
        review_params=SamplingParams(temperature=0,max_tokens=192,seed=0,stop=['\nVerdict:'])
        rows=read(a.out/'verifier_inputs.jsonl');done=0
        with (a.worker_out/'scores.jsonl').open('w',buffering=1) as f:
            for offset in range(0,len(rows),64):
                if time.time()>a.deadline-60:raise TimeoutError('VERIFIER_DEADLINE')
                batch=rows[offset:offset+64];records=[];valid=[r for r in batch if not r['oversized']]
                outputs=llm.generate([dict(prompt_token_ids=r['ids']) for r in valid],review_params,use_tqdm=False) if valid else []
                if len(outputs)!=len(valid):raise ValueError('REVIEW_COVERAGE')
                byid={r['id']:o for r,o in zip(valid,outputs)};scoring=[];positions=[]
                for r in batch:
                    item=dict(id=r['id'],position=r['position'],admitted=False,status='OVERSIZED',score=None,exact=False,
                        input_sha256=r['input_sha256'],review='',source_support=[])
                    if not r['oversized']:
                        o=byid[r['id']]
                        if list(o.prompt_token_ids)!=r['ids'] or not o.outputs:raise ValueError('REVIEW_INPUT_DRIFT')
                        sample=o.outputs[0];accepted,status,support=admit_review(sample.text,r['source_policy'],sample.finish_reason=='length')
                        item.update(review=sample.text,admitted=accepted,status=status,source_support=support)
                        if accepted:
                            ids=tok.encode(tok.decode(r['ids'],skip_special_tokens=False)+sample.text.strip()+'\nVerdict:',add_special_tokens=False)
                            if ids[:len(r['ids'])]!=r['ids'] or len(ids)>=49152:raise ValueError('FINAL_BOUNDARY')
                            item['score_input_sha256']=hashlib.sha256(json.dumps(ids,separators=(',',':')).encode()).hexdigest()
                            scoring.append(dict(prompt_token_ids=ids));positions.append(len(records))
                    records.append(item)
                scored=llm.generate(scoring,params,use_tqdm=False) if scoring else []
                if len(scored)!=len(scoring):raise ValueError('EXACT_COVERAGE')
                for j,o,p in zip(positions,scored,scoring):
                    score,exact=answer_score(o,yes,no)
                    if not exact or score is None or not math.isfinite(score) or list(o.prompt_token_ids)!=p['prompt_token_ids']:raise ValueError('INEXACT_FINAL')
                    records[j].update(score=score,exact=True)
                for r in records:f.write(json.dumps(r)+'\n')
                done+=len(records);write(a.worker_out/'PROGRESS.json',dict(done=done,total=len(rows),labels_read=False))
        write(a.worker_out/'DONE.json',dict(complete=True,rows=done,scores_sha256=sha(a.worker_out/'scores.jsonl'),
            adapter_sha256=expected_sha if adapter else None,labels_read=False))
    finally:
        if llm is not None:llm.llm_engine.engine_core.shutdown()
    sys.stdout.flush();sys.stderr.flush();os._exit(0)


def analyse(a):
    # Called only after hashes for both complete verifier arms have been frozen.
    values={}
    for arm in ('base','new'):
        r=json.loads((a.out/arm/'DONE.json').read_bytes())
        if not r['complete'] or sha(a.out/arm/'scores.jsonl')!=r['scores_sha256']:raise ValueError('ARM_NOT_FROZEN')
        values[arm]={r['position']:r for r in read(a.out/arm/'scores.jsonl')}
    write(a.out/'ALL_OUTPUTS_FROZEN.json',dict(labels_read=False,arms={k:sha(a.out/k/'scores.jsonl') for k in values}))
    with (a.out/'predictions.csv').open(encoding='utf-8',newline='') as f:pred=list(csv.DictReader(f))
    rows=read(a.lab/'data/guardian-judge-eval-data-v1/compli_eval/labels.jsonl')
    if len(rows)!=1893 or [r['id'] for r in rows]!=[r['id'] for r in pred]:raise ValueError('GOLD_JOIN')
    gold={r['id']:r['label'] for r in rows};before=[int(r['label']) for r in pred]
    hard={i for i,r in enumerate(read(a.out/'work/decisions.jsonl')) if r['hard']}
    labels={arm:filtered(before,hard,values[arm]) for arm in values}
    result=dict(complete=True,rows=1893,baseline=metrics(rows,gold,before),arms={},domains={},
        independent_validation=False,private_improvement_measured=False,production_promoted=False,
        status='EXPLORATORY_PREVIOUSLY_USED_EVAL',quota=.4,threshold=0,quota_refill=False)
    for arm,after in labels.items():
        result['arms'][arm]=dict(metrics=metrics(rows,gold,after),removed_fp=sum(x and not y and gold[r['id']]==0 for r,x,y in zip(rows,before,after)),
            lost_tp=sum(x and not y and gold[r['id']]==1 for r,x,y in zip(rows,before,after)),admitted=sum(r['admitted'] for r in values[arm].values()))
    for domain in sorted({r['domain'] for r in rows}):
        ids=[i for i,r in enumerate(rows) if r['domain']==domain];subset=[rows[i] for i in ids]
        result['domains'][domain]=dict(rows=len(ids),baseline=metrics(subset,gold,[before[i] for i in ids]),
            arms={arm:metrics(subset,gold,[after[i] for i in ids]) for arm,after in labels.items()})
    write(a.out/'RESULTS.json',result)


def cleanup(a):
    log=a.out/'work/stage.log';released=[]
    if log.exists():
        for pid in set(map(int,re.findall(r'EngineCore pid=(\d+)',log.read_text(errors='replace')))):
            p=Path('/proc')/str(pid)
            try:owned=(p/'cwd').resolve()==(a.out/'work').resolve() and (p/'comm').read_text().startswith('VLLM::Engine')
            except OSError:continue
            if owned:os.kill(pid,signal.SIGTERM);released.append(pid)
    write(a.out/'OWN_ENGINE_CLEANUP.json',dict(term_pids=released))


def run(a):
    a.out.mkdir(parents=True,exist_ok=False);started=time.monotonic();active=None
    try:
        if subprocess.check_output(['nvidia-smi','--query-gpu=memory.used','--format=csv,noheader,nounits'],text=True).strip()!='0':raise ValueError('GPU_BUSY')
        source=a.lab/'data/guardian-judge-eval-data-v1/compli_eval/inputs.csv'
        if sha(source)!=INPUT_SHA:raise ValueError('SOURCE_DRIFT')
        csv.field_size_limit(2**31-1)
        with source.open(encoding='utf-8',newline='') as f:rows=list(csv.DictReader(f))
        if len(rows)!=1893 or len({r['id'] for r in rows})!=1893:raise ValueError('SOURCE_COVERAGE')
        with (a.out/'inputs.csv').open('w',encoding='utf-8',newline='') as f:
            w=csv.DictWriter(f,fieldnames=['id','prompt','response']);w.writeheader();w.writerows([{k:r[k] for k in w.fieldnames} for r in rows])
        cfg=pipeline_config(a.lab/'models/qwen36-awq');cfg.update(chunk=64,judge_stop_seconds=4300,kill_seconds=4400,watchdog_seconds=4500)
        write(a.out/'config.json',cfg)
        write(a.out/'START.json',dict(rows=1893,source_sha256=sha(Path(__file__)),inputs_sha256=sha(a.out/'inputs.csv'),
            protocol_sha256=sha(ROOT/'docs/judge_20261013/V12_TRANSFER_PROTOCOL.md'),deadline=a.deadline,
            labels_read=False,quality_retries=0,prediction_cache=False,compiler_cache_reused=True,
            research_time_extended=True,production_promoted=False))
        verify_model(a.lab/'models/qwen36-awq',a.lab/'v5-35b-20261019/BASE_MODEL_MANIFEST.json')
        def execute(name,cmd,limit):
            nonlocal active
            with (a.out/(name+'.log')).open('w',buffering=1) as f:
                active=subprocess.Popen(cmd,stdout=f,stderr=subprocess.STDOUT,start_new_session=True,cwd=ROOT)
                code=active.wait(timeout=max(1,min(a.deadline-60,time.time()+limit)-time.time()))
            if code:raise RuntimeError(name+'_EXIT:'+str(code))
            active=None
        common=['--lab',str(a.lab),'--out',str(a.out),'--deadline',str(a.deadline)]
        execute('pipeline',[sys.executable,str(ROOT/'scripts/v9_full_pipeline_dev520.py'),'arm',*common],4550)
        cleanup(a);prepare_verifier(a)
        for arm in ('base','new'):
            execute('verifier-'+arm,[sys.executable,str(Path(__file__)),'worker',*common,'--arm',arm],1250)
        analyse(a)
        write(a.out/'DONE.json',dict(complete=True,seconds=time.monotonic()-started,results_sha256=sha(a.out/'RESULTS.json')))
    except Exception as e:
        write(a.out/'FAIL.json',dict(error=str(e),traceback=traceback.format_exc(),seconds=time.monotonic()-started));raise
    finally:
        if active is not None:
            try:os.killpg(active.pid,signal.SIGTERM)
            except ProcessLookupError:pass
            if active.poll() is None:
                try:active.wait(timeout=30)
                except subprocess.TimeoutExpired:os.killpg(active.pid,signal.SIGKILL);active.wait()
        cleanup(a)
        from scripts.v7_control import export
        export(a.out)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['run','worker'])
    for k in ('lab','out'):p.add_argument('--'+k,type=Path,required=True)
    p.add_argument('--deadline',type=float,required=True);p.add_argument('--arm',choices=['base','new'])
    p.add_argument('--training',type=Path);a=p.parse_args()
    run(a) if a.mode=='run' else worker(a)
