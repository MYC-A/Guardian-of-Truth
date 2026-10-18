"""Fresh-base L1 pilot/training with progress, finite budget and resumable artifacts."""
import argparse
import contextlib
import csv
import hashlib
import json
import math
from pathlib import Path
import random
import signal
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src'),str(ROOT/'scripts')]
from v3_data import training_text
from guardian_truth.judge.prompting import render
from scripts.judge_stage import answer_ids

def read(path):return [json.loads(line) for line in path.read_bytes().splitlines()]
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path,data):
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(data,indent=2));temporary.replace(path)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--model',type=Path,required=True)
    parser.add_argument('--data',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--pilot',action='store_true');parser.add_argument('--real-input',type=Path)
    parser.add_argument('--budget-seconds',type=int,default=10800)
    args=parser.parse_args();args.out.mkdir(exist_ok=False);started=time.monotonic()
    import torch
    from transformers import AutoTokenizer,AutoModelForCausalLM
    from peft import LoraConfig,get_peft_model
    torch.set_num_threads(6);torch.manual_seed(20261019);random.seed(20261019)
    torch.backends.cuda.matmul.allow_tf32=True
    verified=json.loads((args.model/'VERIFIED.json').read_bytes())
    assert verified['verified'] and verified['revision']=='cdbee75f17c01a7cc42f958dc650907174af0554'
    tok=AutoTokenizer.from_pretrained(args.model,local_files_only=True,trust_remote_code=False)
    yes,no=answer_ids(tok)
    rows=read(args.data/('candidate_rows.jsonl' if args.pilot else 'train.jsonl'))
    if args.pilot: rows=sorted(rows,key=lambda r:(-r['n_tokens'],r['id']))[:10]
    training=[]
    with (args.out/'requests.jsonl').open('w',encoding='utf8',buffering=1) as requests:
        def encode(row,partition):
            text,n=training_text(tok,row,32768);ids=tok.encode(text,add_special_tokens=False)
            assert n==len(ids)==row['n_tokens'],'TOKEN_COUNT_DRIFT'
            rec=dict(id=row['id'],partition=partition,tokens=n,
                text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                tokens_sha256=hashlib.sha256(json.dumps(ids,separators=(',',':')).encode()).hexdigest())
            requests.write(json.dumps(dict(rec,text=text))+'\n')
            # Pilot uses a constant target, never holdout labels or optimizer steps.
            return dict(rec,ids=ids,label=0 if args.pilot else row['label'])
        training=[encode(r,'technical_pilot' if args.pilot else 'train') for r in rows]
    meta=dict(base=verified['revision'],pilot=args.pilot,seed=20261019,rows=len(training),
        script_sha256=sha(Path(__file__)),data_sha256=sha(args.data/('candidate_rows.jsonl' if args.pilot else 'train.jsonl')),
        answer_ids={'yes':sorted(yes),'no':sorted(no)},context_trimmed=False,human_reviewed=False,
        status='EXPLORATORY_ONLY',objective='BCE exact YES-vs-NO next-token log-odds',
        rank=16,alpha=32,dropout=.05,learning_rate=.0001,effective_batch=16)
    write(args.out/'START.json',meta)
    model=AutoModelForCausalLM.from_pretrained(args.model,local_files_only=True,trust_remote_code=False,
        dtype=torch.bfloat16,attn_implementation='sdpa').to('cuda')
    model.config.use_cache=False
    model=get_peft_model(model,LoraConfig(task_type='CAUSAL_LM',r=16,lora_alpha=32,lora_dropout=.05,
        target_modules='all-linear',bias='none'))
    trainable=[p for n,p in model.named_parameters() if p.requires_grad]
    assert all('lora_' in n for n,p in model.named_parameters() if p.requires_grad)
    meta['trainable_parameters']=sum(p.numel() for p in trainable)
    yi=torch.tensor(sorted(yes),device='cuda');ni=torch.tensor(sorted(no),device='cuda')
    def odds(rec):
        ids=torch.tensor([rec['ids']],device='cuda')
        logits=model(input_ids=ids,use_cache=False,logits_to_keep=1).logits[0,-1,:].float()
        return torch.logsumexp(logits[yi],0)-torch.logsumexp(logits[ni],0)
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant':False})
    model.enable_input_require_grads();model.train()
    if args.pilot:
        records=[]
        for rec in training:
            model.zero_grad(set_to_none=True);torch.cuda.synchronize();t=time.monotonic()
            score=odds(rec);torch.nn.functional.binary_cross_entropy_with_logits(score,torch.zeros((),device='cuda')).backward()
            torch.cuda.synchronize();records.append(dict(id=rec['id'],tokens=rec['tokens'],seconds=time.monotonic()-t,
                peak_bytes=torch.cuda.max_memory_allocated()))
            print(json.dumps(dict(event='pilot',**records[-1])),flush=True)
        meta.update(complete=True,optimizer_updates=0,pilot_rows=records,seconds=time.monotonic()-started,
                    tokens_per_second=sum(r['tokens'] for r in records)/sum(r['seconds'] for r in records))
        write(args.out/'DONE.json',meta);return
    stopped=False
    def stop(_signal,_frame):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop)
    optimizer=torch.optim.AdamW(trainable,lr=.0001,weight_decay=.01,fused=True)
    order=list(range(len(training)));random.Random(20261019).shuffle(order)
    train_started=time.monotonic();steps=0;rows_done=0
    def checkpoint(name):
        folder=args.out/name;folder.mkdir(exist_ok=False)
        model.save_pretrained(folder/'adapter',safe_serialization=True)
        torch.save(dict(optimizer=optimizer.state_dict(),cpu_rng=torch.get_rng_state(),
            cuda_rng=torch.cuda.get_rng_state_all(),order=order,rows_done=rows_done,steps=steps),folder/'state.pt')
        write(folder/'CHECKPOINT.json',dict(meta,rows_done=rows_done,steps=steps,
            adapter_sha256=sha(folder/'adapter/adapter_model.safetensors')))
        return folder
    with (args.out/'training.jsonl').open('w',encoding='utf8',buffering=1) as log:
        for offset in range(0,len(order),16):
            if stopped or time.monotonic()-train_started>args.budget_seconds:break
            batch=order[offset:offset+16];optimizer.zero_grad(set_to_none=True);loss_sum=0
            for key in batch:
                score=odds(training[key]);target=torch.tensor(float(training[key]['label']),device='cuda')
                loss=torch.nn.functional.binary_cross_entropy_with_logits(score,target)
                assert bool(torch.isfinite(loss)),'NONFINITE_LOSS'
                (loss/len(batch)).backward();loss_sum+=float(loss.detach())
            norm=float(torch.nn.utils.clip_grad_norm_(trainable,1.));assert math.isfinite(norm)
            for group in optimizer.param_groups:group['lr']=.0001*min(1.,(steps+1)/5)
            optimizer.step();steps+=1;rows_done=offset+len(batch)
            progress=dict(step=steps,rows_done=rows_done,rows_total=len(training),loss=loss_sum/len(batch),
                          grad_norm=norm,seconds=time.monotonic()-train_started)
            log.write(json.dumps(progress)+'\n');write(args.out/'PROGRESS.json',progress)
            print(json.dumps(dict(event='train',**progress)),flush=True)
            if steps%20==0:checkpoint(f'checkpoint-{steps:04d}')
    assert steps>0,'ZERO_OPTIMIZER_STEPS'
    final=checkpoint('final');model.save_pretrained(args.out/'adapter',safe_serialization=True)
    meta.update(training_steps=steps,rows_done=rows_done,epoch_fraction=rows_done/len(training),
        epoch_complete=rows_done==len(training),training_seconds=time.monotonic()-train_started,
        adapter_sha256=sha(args.out/'adapter/adapter_model.safetensors'))
    write(args.out/'TRAINED.json',meta)
    del optimizer;model.gradient_checkpointing_disable();model.eval();torch.cuda.empty_cache()
    if stopped:return
    plans={}
    for name in ('dev','holdout'):
        plans[name]=[]
        for r in read(args.data/(name+'_inputs.jsonl')):
            assert set(r)=={'id','prompt','response'}
            text=render(tok,r['prompt'],r['response'],[])
            n=len(tok.encode(text,add_special_tokens=False));assert n<=32768
            plans[name].append(dict(id=r['id'],ids=tok.encode(text,add_special_tokens=False),tokens=n))
    if args.real_input:
        csv.field_size_limit(2**31-1)
        with args.real_input.open(encoding='utf8',newline='') as source: external=list(csv.DictReader(source))
        assert set(external[0])=={'id','prompt','response'}
        plans['regression_seen']=[]
        for r in external:
            text=render(tok,r['prompt'],r['response'],[]);ids=tok.encode(text,add_special_tokens=False)
            assert len(ids)<=98304,'EVAL_CONTEXT_OVER_CAP'
            plans['regression_seen'].append(dict(id=r['id'],ids=ids,tokens=len(ids)))
    with (args.out/'scores.jsonl').open('w',encoding='utf8',buffering=1) as scores:
        with torch.inference_mode():
            for arm in ('base','adapter'):
                with (model.disable_adapter() if arm=='base' else contextlib.nullcontext()):
                    for name,records in plans.items():
                        for i,rec in enumerate(records):
                            if stopped:
                                write(args.out/'INTERRUPTED.json',dict(meta,phase='evaluation',partition=name,arm=arm))
                                return
                            try:
                                value=float(odds(rec));assert math.isfinite(value)
                                result=dict(id=rec['id'],partition=name,arm=arm,score=value,exact=True,tokens=rec['tokens'])
                            except torch.cuda.OutOfMemoryError:
                                torch.cuda.empty_cache();result=dict(id=rec['id'],partition=name,arm=arm,score=None,exact=False,error='OOM')
                            scores.write(json.dumps(result)+'\n')
                            if i%40==0:print(json.dumps(dict(event='evaluate',arm=arm,partition=name,rows=i+1)),flush=True)
    meta.update(complete=True,wall_seconds=time.monotonic()-started,peak_gpu_bytes=torch.cuda.max_memory_allocated())
    write(args.out/'DONE.json',meta);print(json.dumps(dict(event='complete',**meta)),flush=True)

if __name__=='__main__':main()
