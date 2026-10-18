"""One frozen classification-LoRA epoch, with gold-free paired evaluation."""
import argparse,contextlib,hashlib,json,math,random,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from guardian_truth.judge import blind_review as br
from guardian_truth.judge.prompting import render,QUESTION
from scripts.judge_consent_verifier_v2_20261018 import AUTH_SYSTEM,AUTH_QUESTION,source_from_base
from scripts.judge_stage import answer_ids

def read(p):return [json.loads(l) for l in p.read_bytes().splitlines() if l.strip()]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,x):p.write_bytes((json.dumps(x,indent=2)+'\n').encode())

def prompt(tok,row):
    text=render(tok,row['prompt'],row['response'],[])
    if row['task']=='authorization':
        text=br.render_chat(tok,AUTH_SYSTEM,source_from_base(text)+'\n'+AUTH_QUESTION)
    elif row['task']!='whole_turn':raise ValueError('UNKNOWN_TASK')
    return text

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--model',type=Path,required=True);ap.add_argument('--data',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
    a.out.mkdir(exist_ok=False);start=time.monotonic()
    import torch
    from transformers import AutoTokenizer,AutoModelForCausalLM
    from peft import LoraConfig,get_peft_model
    torch.set_num_threads(6);torch.manual_seed(20261018);random.seed(20261018)
    torch.backends.cuda.matmul.allow_tf32=True
    verified=json.loads((a.model/'VERIFIED.json').read_bytes());assert verified['verified']
    assert verified['revision']=='cdbee75f17c01a7cc42f958dc650907174af0554'
    manifest=json.loads((a.data/'MANIFEST.json').read_bytes())
    for name,rec in manifest['files'].items():
        if name.endswith('_gold.jsonl'):continue
        assert sha(a.data/name)==rec['sha256'],name
    tok=AutoTokenizer.from_pretrained(a.model,local_files_only=True,trust_remote_code=False)
    yes,no=answer_ids(tok)
    train=[];excluded=[];evals={};request_count=0
    with (a.out/'requests.jsonl').open('w',encoding='utf-8',buffering=1) as f:
        def encode(row,partition):
            nonlocal request_count
            assert set(row).isdisjoint({'oracle','gold'}), 'UNEXPECTED_GOLD_FIELD'
            text=prompt(tok,row);ids=tok.encode(text,add_special_tokens=False)
            record=dict(partition=partition,id=row['id'],task=row['task'],tokens=len(ids),
                row_sha256=br.sha(row['prompt']+'\0'+row['response']),input_sha256=br.sha(text),input_token_sha256=br.token_sha(tok,text))
            f.write(json.dumps(dict(record,text=text),ensure_ascii=True)+'\n');request_count+=1
            return dict(record,ids=ids,label=row.get('label'))
        for row in read(a.data/'train.jsonl'):
            item=encode(row,'train')
            if item['tokens']>8192:excluded.append({k:v for k,v in item.items() if k!='ids'})
            else:train.append(item)
        for name in ('natural_validation','synthetic_diagnostic','dev520'):
            rows=read(a.data/(name+'_inputs.jsonl'))
            assert all('label' not in r for r in rows),'EVALUATION_GOLD_LEAK'
            evals[name]=[encode(row,name) for row in rows]
            assert all(r['tokens']<=16384 for r in evals[name]),'EVAL_OVER_CAP_NO_TRIMMING'
    meta=dict(schema='classification-lora-pilot-v1',base=verified,seed=20261018,rank=16,alpha=32,dropout=.05,
        learning_rate=.0001,epoch=1,effective_batch=16,microbatch=1,warmup_steps=5,
        train_rows=len(train),excluded=excluded,evaluation_rows={k:len(v) for k,v in evals.items()},
        input_context_trimmed=False,evaluation_gold_loaded=False,requests=request_count,
        script_sha256=sha(Path(__file__)),data_manifest_sha256=sha(a.data/'MANIFEST.json'),
        answer_ids=dict(yes=sorted(yes),no=sorted(no)),objective='BCE(logsumexp(YES logits)-logsumexp(NO logits))',
        train_optimizer_steps=math.ceil(len(train)/16))
    write(a.out/'START.json',meta)
    print(json.dumps(dict(event='prepared',train=len(train),excluded=len(excluded),eval=meta['evaluation_rows'],seconds=time.monotonic()-start)),flush=True)
    model=AutoModelForCausalLM.from_pretrained(a.model,local_files_only=True,trust_remote_code=False,
        dtype=torch.bfloat16,attn_implementation='sdpa').to('cuda')
    model.config.use_cache=False
    model=get_peft_model(model,LoraConfig(task_type='CAUSAL_LM',r=16,lora_alpha=32,lora_dropout=.05,target_modules='all-linear',bias='none'))
    trainable=[p for n,p in model.named_parameters() if p.requires_grad]
    assert trainable and all('lora_' in n for n,p in model.named_parameters() if p.requires_grad),'BACKBONE_NOT_FROZEN'
    meta['trainable_parameters']=sum(p.numel() for p in trainable)
    meta['total_parameters']=sum(p.numel() for p in model.parameters())
    yi=torch.tensor(sorted(yes),device='cuda');ni=torch.tensor(sorted(no),device='cuda')
    def odds(row):
        x=torch.tensor([row['ids']],device='cuda',dtype=torch.long)
        out=model(input_ids=x,use_cache=False,logits_to_keep=1).logits[0,-1,:].float()
        return torch.logsumexp(out[yi],0)-torch.logsumexp(out[ni],0)
    with (a.out/'scores.jsonl').open('w',encoding='utf-8',buffering=1) as f:
        def evaluate(arm):
            model.eval();t=time.monotonic();count=0
            ctx=model.disable_adapter() if arm=='base' else contextlib.nullcontext()
            with ctx,torch.inference_mode():
                for partition,rows in evals.items():
                    for row in rows:
                        score=float(odds(row));assert math.isfinite(score),'NONFINITE_EVALUATION'
                        record={k:v for k,v in row.items() if k not in ('ids','label')}
                        f.write(json.dumps(dict(record,arm=arm,score=score,exact=True))+'\n');count+=1
                    print(json.dumps(dict(event='evaluate',arm=arm,partition=partition,done=count,seconds=time.monotonic()-t)),flush=True)
            meta.setdefault('evaluation_seconds',{})[arm]=time.monotonic()-t
        evaluate('base')
        model.train();model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant':False});model.enable_input_require_grads()
        optimizer=torch.optim.AdamW(trainable,lr=.0001,weight_decay=.01,fused=True)
        order=list(range(len(train)));random.Random(20261018).shuffle(order)
        t=time.monotonic();steps=0
        with (a.out/'training.jsonl').open('w',encoding='utf-8',buffering=1) as log:
            for offset in range(0,len(order),16):
                keys=order[offset:offset+16];optimizer.zero_grad(set_to_none=True);total=0.
                for k in keys:
                    score=odds(train[k]);target=torch.tensor(float(train[k]['label']),device='cuda')
                    loss=torch.nn.functional.binary_cross_entropy_with_logits(score,target)
                    assert bool(torch.isfinite(loss)),'NONFINITE_TRAINING_LOSS'
                    (loss/len(keys)).backward();total+=float(loss.detach())
                norm=float(torch.nn.utils.clip_grad_norm_(trainable,1.));assert math.isfinite(norm),'NONFINITE_GRADIENT'
                lr=.0001*min(1.,(steps+1)/5)
                for group in optimizer.param_groups:group['lr']=lr
                optimizer.step();steps+=1
                rec=dict(step=steps,rows_done=offset+len(keys),rows=len(train),loss=total/len(keys),grad_norm=norm,lr=lr,
                    seconds=time.monotonic()-t,peak_gpu_bytes=torch.cuda.max_memory_allocated())
                log.write(json.dumps(rec)+'\n');print(json.dumps(dict(event='train',**rec)),flush=True)
        assert steps==meta['train_optimizer_steps']
        assert any(bool(torch.count_nonzero(p.detach())) for n,p in model.named_parameters() if 'lora_B' in n),'ADAPTER_NOT_UPDATED'
        meta.update(training_steps=steps,training_seconds=time.monotonic()-t)
        model.save_pretrained(a.out/'adapter',safe_serialization=True)
        tok.save_pretrained(a.out/'tokenizer')
        write(a.out/'TRAINED.json',dict(meta,seconds=time.monotonic()-start))
        model.gradient_checkpointing_disable()
        evaluate('adapter')
    meta.update(complete=True,wall_seconds=time.monotonic()-start,peak_gpu_bytes=torch.cuda.max_memory_allocated(),
        adapter_files={p.name:dict(bytes=p.stat().st_size,sha256=sha(p)) for p in (a.out/'adapter').iterdir() if p.is_file()})
    write(a.out/'DONE.json',meta)
    print(json.dumps(dict(event='complete',steps=steps,seconds=meta['wall_seconds'])),flush=True)
if __name__=='__main__':main()
