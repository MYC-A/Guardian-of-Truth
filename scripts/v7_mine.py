"""TRAIN-only exact-score mining; whole-pair, domain/family bounded selection."""
import argparse
from collections import defaultdict,Counter
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src'),str(ROOT/'scripts')]
from scripts.v5_35b_common import read,sha,write,verify_model,BASE_REVISION
from scripts.v5_valid46_pipeline import bound_llm
from scripts.v6_verifier_data import OLD_ADAPTER_SHA,SEED

def select(rows,scores,count=96):
    pairs=defaultdict(list);buckets=defaultdict(list)
    for r in rows:pairs[r['pair_id']].append(r)
    for key,pair in pairs.items():
        if len(pair)!=2 or {r['label'] for r in pair}!={0,1}:raise ValueError('NOT_A_PAIR')
        pos=next(r for r in pair if r['label']);neg=next(r for r in pair if not r['label'])
        margin=scores[pos['id']]-scores[neg['id']]
        errors=int(scores[pos['id']]<=0)+int(scores[neg['id']]>0)
        tie=hashlib.sha256((str(SEED)+key).encode()).hexdigest()
        buckets[(pair[0]['domain'],pair[0]['family'])].append((-errors,margin,tie,pair))
    for bucket in buckets.values():bucket.sort(key=lambda x:x[:3])
    chosen=[];uses=Counter()
    while len(chosen)<count:
        before=len(chosen)
        for key in sorted(buckets):
            if uses[key]>=2 or not buckets[key]:continue
            chosen.append(buckets[key].pop(0)[-1]);uses[key]+=1
            if len(chosen)==count:break
        if len(chosen)==before:raise ValueError('INSUFFICIENT_BOUNDED_PAIRS')
    return [r for pair in chosen for r in sorted(pair,key=lambda r:r['label'])]

def run(a):
    a.out.mkdir(exist_ok=False)
    while not (a.data/'PREPARED.json').exists():
        if time.time()>a.deadline:raise TimeoutError('PREPARATION_WAIT')
        time.sleep(5)
    prepared=json.loads((a.data/'PREPARED.json').read_bytes())
    for name in ('candidate_tokens','mining_tokens','replay_tokens'):
        if sha(a.data/(name+'.jsonl'))!=prepared[name+'_sha256']:raise ValueError('INPUT_DRIFT')
    inputs=read(a.data/'mining_tokens.jsonl')
    if any(set(r)!={'id','ids','tokens','text_sha256'} for r in inputs):raise ValueError('GOLD_IN_GPU_INPUT')
    adapter=a.lab/'v5-35b-20261019/train-recovered-v1/adapter'
    if sha(adapter/'adapter_model.safetensors')!=OLD_ADAPTER_SHA:raise ValueError('OLD_ADAPTER_DRIFT')
    verify_model(a.lab/'models/qwen36-awq',a.lab/'v5-35b-20261019/BASE_MODEL_MANIFEST.json')
    from vllm import LLM,SamplingParams
    from vllm.lora.request import LoRARequest
    from scripts.judge_stage import answer_ids,answer_score,engine_kwargs,probe
    cfg=json.loads((ROOT/'submission/JUDGE_OPEN_REVIEW40.json').read_bytes())
    cfg.update(max_model_len=49152,gpu_memory_utilization=.85,max_num_seqs=16,max_num_batched_tokens=8192,
        dtype='bfloat16',multimodal=True,enable_prefix_caching=True,engine_overrides=dict(enforce_eager=True,async_scheduling=False))
    kw,_=engine_kwargs(str(a.lab/'models/qwen36-awq'),cfg)
    request=LoRARequest('v7-train-mining',1,str(adapter))
    llm=bound_llm(LLM,request,a.out/'generation_audit.jsonl',binding_adapter=adapter)(**kw)
    yes,no=answer_ids(llm.get_tokenizer())
    params=SamplingParams(temperature=1,top_p=1,max_tokens=1,logprobs=20,seed=0,allowed_token_ids=sorted(yes|no))
    exact,_=probe(llm,llm.get_tokenizer(),params,yes,no)
    if exact is not True:raise ValueError('EXACT_PROBE')
    scores={};started=time.monotonic()
    with (a.out/'scores.jsonl').open('w',buffering=1) as f:
        for offset in range(0,len(inputs),16):
            if time.time()>a.deadline:raise TimeoutError('MINING_DEADLINE')
            batch=inputs[offset:offset+16];outputs=llm.generate([dict(prompt_token_ids=r['ids']) for r in batch],params,use_tqdm=False)
            if len(outputs)!=len(batch):raise ValueError('OUTPUT_COUNT')
            for r,o in zip(batch,outputs):
                score,exact=answer_score(o,yes,no)
                if not exact or score is None or not math.isfinite(score) or list(o.prompt_token_ids)!=r['ids']:raise ValueError('MINING_SCORE')
                scores[r['id']]=score;f.write(json.dumps(dict(id=r['id'],score=score,exact=True))+'\n')
            write(a.out/'PROGRESS.json',dict(rows_done=len(scores),rows_total=len(inputs),seconds=time.monotonic()-started))
    # Gold accessed only after the isolated model has produced scores.
    rows=read(a.data/'candidate_tokens.jsonl');selected=select(rows,scores)
    replay=read(a.data/'replay_tokens.jsonl');selected+=replay
    from scripts.v7_prepare import dump
    dump(a.out/'train_tokens.jsonl',selected)
    write(a.out/'DONE.json',dict(complete=True,rows=len(selected),new_sft_rows=len(selected)-len(replay),replay_bce_rows=len(replay),
        base_revision=BASE_REVISION,answer_ids=prepared['answer_ids'],train_tokens_sha256=sha(a.out/'train_tokens.jsonl'),
        mining_scores_sha256=sha(a.out/'scores.jsonl'),mining_adapter_sha256=OLD_ADAPTER_SHA,
        tokens=sum(r['tokens'] for r in selected),max_tokens=max(r['tokens'] for r in selected),
        rule='96 whole new pairs; round robin domain/family, <=2 pairs per bucket; errors then pair margin',
        source_sha256=sha(Path(__file__)),gold_in_model_inputs=False,protected_quality_used=False,
        status='EXPLORATORY_ONLY_HUMAN_UNVERIFIED',seconds=time.monotonic()-started))
    sys.stdout.flush();sys.stderr.flush();os._exit(0)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('lab','data','out'):p.add_argument('--'+k,type=Path,required=True)
    p.add_argument('--deadline',type=float,required=True);run(p.parse_args())
