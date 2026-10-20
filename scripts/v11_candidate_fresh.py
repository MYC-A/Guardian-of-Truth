"""Fresh, repeated LoRA vetoes on the frozen production-positive candidate pool."""
import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
import traceback
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src'),str(ROOT/'scripts')]
from scripts.v5_35b_common import read,sha,write,verify_model,BASE_REVISION
from scripts.v5_valid46_pipeline import bound_llm,metrics
from scripts.v8_quote_contract import admit_review


def analyse(a,source,pred,passes):
    metadata=json.loads((source/'EVAL_INDEX.json').read_bytes())['rows']
    lookup={r['original_id']:r for r in metadata if 'dev520' in r['cohorts']}
    rows=[lookup[r['id']] for r in pred];gold={r['id']:r['label'] for r in rows};before=[int(r['label']) for r in pred]
    decisions=read(a.lab/'v10-full-profile-batch64-20261020/evaluation-v10/work/decisions.jsonl')
    if [r['id'] for r in decisions]!=[r['id'] for r in pred]:raise ValueError('BASELINE_DECISION_ORDER')
    hard={r['id'] for r in decisions if r['hard']};labels=[];result=dict(rows=520,candidates=208,
        baseline=metrics(rows,gold,before),passes=[],status='EXPLORATORY_ONLY_HUMAN_UNVERIFIED',
        independent_validation=False,private_improvement_measured=False,production_promoted=False,
        quota=.4,threshold=0,quota_refill=False,chunk=64,review_max_tokens=192,
        repeats_are_not_independent_tasks=True,compiler_cache_reused=True,result_cache=False)
    for number,values in enumerate(passes):
        byid={r['id']:r for r in values}
        after=[int(bool(y) and (r['original_id'] in hard or not byid[r['id']]['admitted'] or byid[r['id']]['score']>0))
            if y else 0 for r,y in zip(rows,before)]
        labels.append(after)
        result['passes'].append(dict(number=number,metrics=metrics(rows,gold,after),
            removed_fp=sum(x and not y and gold[r['id']]==0 for r,x,y in zip(rows,before,after)),
            lost_tp=sum(x and not y and gold[r['id']]==1 for r,x,y in zip(rows,before,after)),
            admitted=sum(r['admitted'] for r in values),unknown=sum(not r['admitted'] for r in values),
            decisions_changed_vs_first=sum(x!=y for x,y in zip(labels[0],after))))
    cached={r['id']:r for r in read(a.lab/'v8-json-quote-replay-20261020/evaluation-v8/new/scores.jsonl')}
    cached_labels=[int(bool(y) and (r['original_id'] in hard or not cached[r['id']]['admitted'] or cached[r['id']]['score']>0)) if y else 0 for r,y in zip(rows,before)]
    result['cached_review_metrics']=metrics(rows,gold,cached_labels)
    result['fresh_vs_cached_decision_changes']=[sum(x!=y for x,y in zip(cached_labels,z)) for z in labels]
    return result


def run(a):
    a.out.mkdir(parents=True,exist_ok=False);started=time.monotonic();llm=None
    try:
        if time.time()>a.deadline-600:raise TimeoutError('INSUFFICIENT_FRESH_CHECK_BUDGET')
        v10=a.lab/'v10-full-profile-batch64-20261020/evaluation-v10';v7=a.lab/'v7-workflow-20261020';source=v7/'prepared-v1'
        receipt=json.loads((v10/'DONE.json').read_bytes())
        if not receipt['complete'] or sha(v10/'RESULTS.json')!=receipt['results_sha256']:raise ValueError('V10_NOT_FROZEN')
        with (v10/'predictions.csv').open(encoding='utf-8',newline='') as f:pred=list(csv.DictReader(f))
        if len(pred)!=520 or sum(int(r['label']) for r in pred)!=208:raise ValueError('CANDIDATE_POOL_COUNT')
        prepared=json.loads((source/'PREPARED.json').read_bytes())
        if sha(source/'eval_tokens.jsonl')!=prepared['eval_tokens_sha256'] or sha(source/'EVAL_INDEX.json')!=prepared['eval_index_sha256']:
            raise ValueError('ORIGINAL_INPUT_DRIFT')
        lookup={r['id']:r for r in read(source/'eval_tokens.jsonl')}
        rows=[lookup['compli_dev::'+r['id']] for r in pred if int(r['label'])]
        if len({r['id'] for r in rows})!=208 or any(set(r)!={'id','ids','tokens','text_sha256','source_policy'} for r in rows):raise ValueError('GOLD_FREE_CANDIDATE_SCHEMA')
        with (a.out/'inputs.jsonl').open('w') as f:
            for row in rows:f.write(json.dumps(row)+'\n')
        write(a.out/'START.json',dict(rows=208,passes=3,threshold=0,quota_refill=False,chunk=64,
            gpu_deadline=a.deadline,input_sha256=sha(a.out/'inputs.jsonl'),source_sha256=sha(Path(__file__)),
            v10_predictions_sha256=sha(v10/'predictions.csv'),reviews_regenerated=True,labels_read=False,
            status='EXPLORATORY_ONLY_HUMAN_UNVERIFIED',source_support_not_semantic_proof=True))
        train=v7/'training-v2/layers16';meta=json.loads((train/'TRAINED.json').read_bytes());adapter=train/'adapter'
        if not meta['epoch_complete'] or meta['rows_done']!=224 or meta['base_revision']!=BASE_REVISION or sha(adapter/'adapter_model.safetensors')!=meta['adapter_sha256']:
            raise ValueError('TRAINED_ADAPTER_DRIFT')
        verify_model(a.lab/'models/qwen36-awq',a.lab/'v5-35b-20261019/BASE_MODEL_MANIFEST.json')
        from vllm import LLM,SamplingParams
        from vllm.lora.request import LoRARequest
        from scripts.judge_stage import answer_ids,answer_score,engine_kwargs,probe
        cfg=json.loads((ROOT/'submission/JUDGE_OPEN_REVIEW40.json').read_bytes())
        cfg.update(max_model_len=49152,gpu_memory_utilization=.85,max_num_seqs=64,max_num_batched_tokens=16384,
            dtype='bfloat16',multimodal=True,enable_prefix_caching=True,engine_overrides=dict(enforce_eager=True,async_scheduling=False))
        kwargs,_=engine_kwargs(str(a.lab/'models/qwen36-awq'),cfg)
        request=LoRARequest('v11-fresh-candidate',1,str(adapter))
        llm=bound_llm(LLM,request,a.out/'generation_audit.jsonl',binding_adapter=adapter,expected_source_modules=100)(**kwargs)
        tok=llm.get_tokenizer();yes,no=answer_ids(tok)
        if sorted(yes)!=prepared['answer_ids']['yes'] or sorted(no)!=prepared['answer_ids']['no']:raise ValueError('ANSWER_ID_DRIFT')
        params=SamplingParams(temperature=1,top_p=1,max_tokens=1,logprobs=20,seed=0,allowed_token_ids=sorted(yes|no))
        exact,info=probe(llm,tok,params,yes,no)
        if exact is not True:raise ValueError('EXACT_PROBE')
        write(a.out/'PROBE.json',dict(exact=True,info=info))
        review_params=SamplingParams(temperature=0,max_tokens=192,seed=0,stop=['\nVerdict:'])
        passes=[];times=[]
        for repeat in range(3):
            values=[];begin=time.monotonic()
            with (a.out/('pass-'+str(repeat)+'.jsonl')).open('w',buffering=1) as f:
                for offset in range(0,208,64):
                    if time.time()>a.deadline-90:raise TimeoutError('FRESH_CANDIDATE_DEADLINE')
                    batch=rows[offset:offset+64];outputs=llm.generate([dict(prompt_token_ids=r['ids']) for r in batch],review_params,use_tqdm=False)
                    if len(outputs)!=len(batch):raise ValueError('REVIEW_COUNT')
                    records=[];scoring=[];positions=[]
                    for r,o in zip(batch,outputs):
                        if list(o.prompt_token_ids)!=r['ids'] or not o.outputs:raise ValueError('REVIEW_INPUT_DRIFT')
                        sample=o.outputs[0];accepted,status,support=admit_review(sample.text,r['source_policy'],sample.finish_reason=='length')
                        item=dict(id=r['id'],repeat=repeat,review=sample.text,admitted=accepted,status=status,
                            source_support=support,score=None,exact=False,input_sha256=r['text_sha256'])
                        if accepted:
                            ids=tok.encode(tok.decode(r['ids'],skip_special_tokens=False)+sample.text.strip()+'\nVerdict:',add_special_tokens=False)
                            if ids[:len(r['ids'])]!=r['ids'] or len(ids)>=49152:raise ValueError('FINAL_TOKEN_PREFIX_OR_CAP')
                            item['score_input_sha256']=hashlib.sha256(json.dumps(ids,separators=(',',':')).encode()).hexdigest()
                            scoring.append(dict(prompt_token_ids=ids));positions.append(len(records))
                        records.append(item)
                    scored=llm.generate(scoring,params,use_tqdm=False) if scoring else []
                    if len(scored)!=len(scoring):raise ValueError('FINAL_COUNT')
                    for position,o,prompt in zip(positions,scored,scoring):
                        score,exact=answer_score(o,yes,no)
                        if not exact or score is None or not math.isfinite(score) or list(o.prompt_token_ids)!=prompt['prompt_token_ids']:raise ValueError('INEXACT_OR_FINAL_TOKEN_DRIFT')
                        records[position].update(score=score,exact=True)
                    for record in records:f.write(json.dumps(record)+'\n')
                    values.extend(records)
                    write(a.out/'PROGRESS.json',dict(repeat=repeat,rows_done=len(values),rows_total=208,seconds=time.monotonic()-started))
            passes.append(values);times.append(time.monotonic()-begin)
        llm.llm_engine.engine_core.shutdown();llm=None
        result=analyse(a,source,pred,passes);result.update(pass_seconds=times,total_seconds=time.monotonic()-started,
            adapter_sha256=meta['adapter_sha256'],runtime_scope='candidate verification only; full baseline measured separately')
        write(a.out/'RESULTS.json',result)
        write(a.out/'DONE.json',dict(complete=True,passes=3,rows_per_pass=208,seconds=time.monotonic()-started,results_sha256=sha(a.out/'RESULTS.json')))
    except Exception as e:
        write(a.out/'FAIL.json',dict(error=str(e),traceback=traceback.format_exc(),seconds=time.monotonic()-started));raise
    finally:
        if llm is not None:llm.llm_engine.engine_core.shutdown()
        from scripts.v7_control import export
        export(a.out)
    sys.stdout.flush();sys.stderr.flush();os._exit(0)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for key in ('lab','out'):p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--deadline',type=float,required=True);run(p.parse_args())
