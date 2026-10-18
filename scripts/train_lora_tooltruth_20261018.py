"""One frozen v2 epoch, controlled base pair and gold-free full Guardian transfer."""
import argparse,contextlib,csv,hashlib,json,math,random,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from guardian_truth.judge.prompting import render
from scripts.judge_stage import answer_ids


def read(p):return [json.loads(l) for l in p.read_bytes().splitlines()]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,x):p.write_bytes((json.dumps(x,indent=2)+'\n').encode())


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--model',type=Path,required=True)
    ap.add_argument('--data',type=Path,required=True);ap.add_argument('--real-input',type=Path,required=True)
    ap.add_argument('--out',type=Path,required=True);a=ap.parse_args();a.out.mkdir(exist_ok=False)
    start=time.monotonic();csv.field_size_limit(2**31-1)
    import torch
    from transformers import AutoTokenizer,AutoModelForCausalLM
    from peft import LoraConfig,get_peft_model
    torch.set_num_threads(6);torch.manual_seed(20261018);random.seed(20261018)
    torch.backends.cuda.matmul.allow_tf32=True
    for n,r in json.loads((a.data/'GPU_MANIFEST.json').read_bytes())['files'].items():assert sha(a.data/n)==r['sha256'],n
    assert not list(a.data.glob('*gold*')),'EVAL_GOLD_UPLOADED'
    verified=json.loads((a.model/'VERIFIED.json').read_bytes());assert verified['verified']
    assert verified['revision']=='cdbee75f17c01a7cc42f958dc650907174af0554'
    tok=AutoTokenizer.from_pretrained(a.model,local_files_only=True,trust_remote_code=False)
    yes,no=answer_ids(tok);plans={};training=[]
    with (a.out/'requests.jsonl').open('w',encoding='utf8',buffering=1) as f:
        def encode(r,partition):
            assert 'oracle' not in r and 'gold' not in r
            rendered=render(tok,r['prompt'],r['response'],[]);ids=tok.encode(rendered,add_special_tokens=False)
            rec=dict(partition=partition,id=r['id'],task='whole_turn',tokens=len(ids),
                row_sha256=hashlib.sha256((r['prompt']+'\0'+r['response']).encode('utf8','surrogatepass')).hexdigest(),
                input_sha256=hashlib.sha256(rendered.encode('utf8','surrogatepass')).hexdigest(),
                input_token_sha256=hashlib.sha256(json.dumps(ids,separators=(',',':')).encode()).hexdigest())
            f.write(json.dumps(dict(rec,text=rendered),ensure_ascii=True)+'\n')
            return dict(rec,ids=ids,label=r.get('label'))
        training=[encode(r,'train') for r in read(a.data/'train.jsonl')]
        assert len(training)==666 and all(r['task']=='whole_turn' for r in read(a.data/'train.jsonl'))
        assert all(r['tokens']<=8192 for r in training),'TRAIN_OVER_CAP_NO_TRIMMING'
        for name in ('natural_validation','tooltruth_validation'):
            rs=read(a.data/(name+'_inputs.jsonl'));assert all('label' not in r for r in rs)
            plans[name]=[encode(r,name) for r in rs]
        with a.real_input.open(encoding='utf8',newline='') as inp:
            rr=list(csv.DictReader(inp));assert len(rr)==397 and set(rr[0])=={'id','prompt','response'}
        plans['regression_seen']=[encode(r,'regression_seen') for r in rr]
        assert all(r['tokens']<=98304 for rs in plans.values() for r in rs),'EVAL_OVER_CAP_NO_TRIMMING'
    meta=dict(schema='tooltruth-lora-v2',base=verified['revision'],seed=20261018,training_rows=666,
        natural_validation_rows=len(plans['natural_validation']),controlled_validation_rows=len(plans['tooltruth_validation']),
        real_rows=397,train_max_tokens=max(r['tokens'] for r in training),
        evaluation_max_tokens={k:max(r['tokens'] for r in rs) for k,rs in plans.items()},
        script_sha256=sha(Path(__file__)),gpu_manifest_sha256=sha(a.data/'GPU_MANIFEST.json'),
        real_input_sha256=sha(a.real_input),input_context_trimmed=False,evaluation_gold_loaded=False,
        answer_ids=dict(yes=sorted(yes),no=sorted(no)),rank=16,alpha=32,dropout=.05,lr=.0001,
        objective='BCE(logsumexp(YES logits)-logsumexp(NO logits))',epoch=1,effective_batch=16,
        expected_steps=42)
    write(a.out/'START.json',meta);print(json.dumps(dict(event='prepared',**meta)),flush=True)
    model=AutoModelForCausalLM.from_pretrained(a.model,local_files_only=True,trust_remote_code=False,
        dtype=torch.bfloat16,attn_implementation='sdpa').to('cuda');model.config.use_cache=False
    model=get_peft_model(model,LoraConfig(task_type='CAUSAL_LM',r=16,lora_alpha=32,lora_dropout=.05,target_modules='all-linear',bias='none'))
    trainable=[p for n,p in model.named_parameters() if p.requires_grad]
    assert trainable and all('lora_' in n for n,p in model.named_parameters() if p.requires_grad)
    meta['trainable_parameters']=sum(p.numel() for p in trainable)
    yi=torch.tensor(sorted(yes),device='cuda');ni=torch.tensor(sorted(no),device='cuda')
    def odds(r):
        x=torch.tensor([r['ids']],device='cuda');logits=model(input_ids=x,use_cache=False,logits_to_keep=1).logits[0,-1,:].float()
        return torch.logsumexp(logits[yi],0)-torch.logsumexp(logits[ni],0)
    with (a.out/'scores.jsonl').open('w',encoding='utf8',buffering=1) as scores:
        def evaluate(arm,partitions):
            model.eval();t=time.monotonic();count=0
            with (model.disable_adapter() if arm=='base' else contextlib.nullcontext()),torch.inference_mode():
                for name in partitions:
                    for r in plans[name]:
                        s=float(odds(r));assert math.isfinite(s),'NONFINITE_SCORE'
                        scores.write(json.dumps(dict({k:v for k,v in r.items() if k not in ('ids','label')},arm=arm,score=s,exact=True))+'\n');count+=1
                        if count%40==0:print(json.dumps(dict(event='evaluate',arm=arm,partition=name,rows=count,seconds=time.monotonic()-t)),flush=True)
            meta.setdefault('evaluation_seconds',{})[arm]=time.monotonic()-t
        evaluate('base',('natural_validation','tooltruth_validation'))
        model.train();model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant':False});model.enable_input_require_grads()
        optimizer=torch.optim.AdamW(trainable,lr=.0001,weight_decay=.01,fused=True)
        order=list(range(len(training)));random.Random(20261018).shuffle(order);t=time.monotonic();steps=0
        with (a.out/'training.jsonl').open('w',encoding='utf8',buffering=1) as log:
            for offset in range(0,len(order),16):
                keys=order[offset:offset+16];optimizer.zero_grad(set_to_none=True);loss_sum=0.
                for k in keys:
                    score=odds(training[k]);target=torch.tensor(float(training[k]['label']),device='cuda')
                    loss=torch.nn.functional.binary_cross_entropy_with_logits(score,target)
                    assert bool(torch.isfinite(loss));(loss/len(keys)).backward();loss_sum+=float(loss.detach())
                norm=float(torch.nn.utils.clip_grad_norm_(trainable,1.));assert math.isfinite(norm)
                for group in optimizer.param_groups:group['lr']=.0001*min(1.,(steps+1)/5)
                optimizer.step();steps+=1
                rec=dict(step=steps,rows_done=offset+len(keys),loss=loss_sum/len(keys),grad_norm=norm,seconds=time.monotonic()-t)
                log.write(json.dumps(rec)+'\n');print(json.dumps(dict(event='train',**rec)),flush=True)
        assert steps==42 and any(bool(torch.count_nonzero(p.detach())) for n,p in model.named_parameters() if 'lora_B' in n)
        meta.update(training_steps=steps,training_seconds=time.monotonic()-t)
        model.save_pretrained(a.out/'adapter',safe_serialization=True);tok.save_pretrained(a.out/'tokenizer')
        meta['adapter_sha256']=sha(a.out/'adapter/adapter_model.safetensors')
        write(a.out/'TRAINED.json',meta);model.gradient_checkpointing_disable();del optimizer
        evaluate('adapter',('natural_validation','tooltruth_validation','regression_seen'))
    meta.update(complete=True,wall_seconds=time.monotonic()-start,peak_gpu_bytes=torch.cuda.max_memory_allocated())
    write(a.out/'DONE.json',meta);print(json.dumps(dict(event='complete',**meta)),flush=True)


if __name__=='__main__':main()
