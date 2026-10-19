"""Offline native-vLLM Qwen4B+LoRA exact scores; source text, no hints, no gold."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from guardian_truth.judge.ensemble import ADAPTER_SHA256
from guardian_truth.judge.prompting import render
from scripts.judge_stage import answer_ids,answer_score,engine_kwargs,emit,read_jsonl,PROBE_PROMPT,PROBE_RESPONSE


def main():
    p=argparse.ArgumentParser()
    for name in ('model','adapter','input','output','config'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--stop-at',type=float,required=True);a=p.parse_args();started=time.monotonic()
    adapter=a.adapter/'adapter_model.safetensors'
    if hashlib.sha256(adapter.read_bytes()).hexdigest()!=ADAPTER_SHA256:raise ValueError('ADAPTER_HASH_MISMATCH')
    cfg=json.loads(a.config.read_bytes());rows=read_jsonl(a.input)
    from vllm import LLM,SamplingParams
    from vllm.lora.request import LoRARequest
    kwargs,dropped=engine_kwargs(str(a.model),cfg)
    kwargs.update(enable_lora=True,max_lora_rank=16,max_loras=1,max_cpu_loras=1)
    llm=LLM(**kwargs);tok=llm.get_tokenizer();yes,no=answer_ids(tok)
    params=SamplingParams(temperature=1.0,top_p=1.0,max_tokens=1,logprobs=20,seed=0,allowed_token_ids=sorted(yes|no))
    request=LoRARequest('guardian-v4',1,str(a.adapter.resolve()))
    probe_text=render(tok,PROBE_PROMPT,PROBE_RESPONSE,[])
    probe=llm.generate([probe_text],params,use_tqdm=False,lora_request=request)
    _,exact=answer_score(probe[0],yes,no)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('w',encoding='utf-8',buffering=1) as out:
        emit(out,[dict(event='ready',exact=exact,adapter_sha256=ADAPTER_SHA256,dropped=dropped,
            yes_ids=sorted(yes),no_ids=sorted(no),max_model_len=cfg['max_model_len'])])
        if not exact:return 3
        built=[];failures=0
        for row in rows:
            if time.time()>=a.stop_at:break
            try:
                text=render(tok,row['prompt'],row['response'],[])
                ids=tok.encode(text,add_special_tokens=False)
                if len(ids)+1>int(cfg['max_model_len']):raise ValueError('SECONDARY_CONTEXT_OVER_CAP')
                built.append((row['key'],ids,hashlib.sha256(text.encode('utf-8')).hexdigest()))
            except Exception as error:
                failures+=1;emit(out,[dict(key=row['key'],score=None,exact=False,error=type(error).__name__+':'+str(error))])
        chunk=int(cfg.get('chunk',16));scored=0
        for lo in range(0,len(built),chunk):
            if time.time()>=a.stop_at:break
            batch=built[lo:lo+chunk]
            try:
                outputs=llm.generate([dict(prompt_token_ids=b[1]) for b in batch],params,use_tqdm=False,lora_request=request)
                if len(outputs)!=len(batch):raise ValueError('SECONDARY_OUTPUT_COUNT')
                for (key,ids,text_sha),o in zip(batch,outputs):
                    if list(o.prompt_token_ids)!=ids:raise ValueError('SECONDARY_TOKEN_RECEIPT_MISMATCH')
                    score,exact=answer_score(o,yes,no)
                    emit(out,[dict(key=key,score=score,exact=exact,tokens=len(ids),text_sha256=text_sha,
                        tokens_sha256=hashlib.sha256(json.dumps(ids,separators=(',',':')).encode()).hexdigest())])
                    scored+=int(exact)
            except Exception as error:
                failures+=len(batch)
                for key,_,_ in batch:emit(out,[dict(key=key,score=None,exact=False,error=type(error).__name__)])
                break
        emit(out,[dict(event='done',rows=len(rows),exact_rows=scored,failures=failures,seconds=time.monotonic()-started)])
    return 0


if __name__=='__main__':
    code=main();sys.stdout.flush();sys.stderr.flush();os._exit(code or 0)
