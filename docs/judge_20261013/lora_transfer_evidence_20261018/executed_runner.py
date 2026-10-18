"""Frozen inference-only transfer check, no labels or score tuning."""
import argparse,csv,hashlib,json,math,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from guardian_truth.judge.prompting import render
from guardian_truth.judge import blind_review as br
from scripts.judge_stage import answer_ids

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--model',type=Path,required=True);ap.add_argument('--adapter',type=Path,required=True);ap.add_argument('--data',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
    a.out.mkdir(exist_ok=False);start=time.monotonic();csv.field_size_limit(2**31-1)
    assert sha(a.adapter/'adapter_model.safetensors')=='7e14c036d15d112e52433d2e4ad970ef0b9c9bda956c546eb3bcc06c2813d1b5'
    import torch
    from transformers import AutoModelForCausalLM,AutoTokenizer
    from peft import PeftModel
    torch.set_num_threads(6);torch.manual_seed(20261018);torch.backends.cuda.matmul.allow_tf32=True
    tok=AutoTokenizer.from_pretrained(a.model,local_files_only=True,trust_remote_code=False)
    yes,no=answer_ids(tok);plans={};sources={};over=[]
    with (a.out/'requests.jsonl').open('w',encoding='utf-8',buffering=1) as f:
        for name,expected in [('compli_eval',1893),('regression_seen',397)]:
            p=a.data/name/'inputs.csv';sources[name]=sha(p)
            with p.open(encoding='utf-8',newline='') as inp:
                reader=csv.DictReader(inp);assert set(reader.fieldnames)=={'id','prompt','response'};rows=list(reader)
            assert len(rows)==expected;plans[name]=[]
            for key,r in enumerate(rows):
                text=render(tok,r['prompt'],r['response'],[]);ids=tok.encode(text,add_special_tokens=False)
                rec=dict(dataset=name,key=key,id=r['id'],row_sha256=br.sha(r['prompt']+'\0'+r['response']),
                    input_sha256=br.sha(text),input_token_sha256=br.token_sha(tok,text),tokens=len(ids))
                f.write(json.dumps(dict(rec,text=text),ensure_ascii=True)+'\n')
                if len(ids)>98304:over.append(rec)
                plans[name].append(dict(rec,ids=ids))
    meta=dict(schema='frozen-lora-transfer-v1',script_sha256=sha(Path(__file__)),sources=sources,
        adapter_sha256=sha(a.adapter/'adapter_model.safetensors'),rows={k:len(v) for k,v in plans.items()},
        max_tokens={k:max(r['tokens'] for r in v) for k,v in plans.items()},over_cap=over,
        labels_loaded=False,context_trimmed=False,training_steps_added=0)
    (a.out/'START.json').write_text(json.dumps(meta,indent=2)+'\n');assert not over,'FULL_COVERAGE_OVER_CAP'
    base=AutoModelForCausalLM.from_pretrained(a.model,local_files_only=True,trust_remote_code=False,
        dtype=torch.bfloat16,attn_implementation='sdpa').to('cuda');base.config.use_cache=False
    model=PeftModel.from_pretrained(base,a.adapter,is_trainable=False);model.eval()
    yi=torch.tensor(sorted(yes),device='cuda');ni=torch.tensor(sorted(no),device='cuda')
    with (a.out/'scores.jsonl').open('w',encoding='utf-8',buffering=1) as f:
        from contextlib import nullcontext
        usage={}
        # Finish external paired comparison before real paired comparison.
        for name,rows in plans.items():
            for arm in ('base','adapter'):
                t=time.monotonic()
                with (model.disable_adapter() if arm=='base' else nullcontext()),torch.inference_mode():
                    for i,r in enumerate(rows):
                        x=torch.tensor([r['ids']],device='cuda',dtype=torch.long)
                        logits=model(input_ids=x,use_cache=False,logits_to_keep=1).logits[0,-1,:].float()
                        score=float(torch.logsumexp(logits[yi],0)-torch.logsumexp(logits[ni],0));assert math.isfinite(score)
                        rec={k:v for k,v in r.items() if k!='ids'};rec.update(arm=arm,score=score,exact=True)
                        f.write(json.dumps(rec)+'\n')
                        if (i+1)%100==0:print(json.dumps(dict(event='scores',dataset=name,arm=arm,done=i+1,total=len(rows),seconds=time.monotonic()-t)),flush=True)
                usage[name+':'+arm]=time.monotonic()-t
                print(json.dumps(dict(event='arm_done',dataset=name,arm=arm,seconds=usage[name+':'+arm])),flush=True)
    meta.update(complete=True,usage=usage,wall_seconds=time.monotonic()-start,peak_gpu_bytes=torch.cuda.max_memory_allocated())
    (a.out/'DONE.json').write_text(json.dumps(meta,indent=2)+'\n');print(json.dumps(dict(event='complete',seconds=meta['wall_seconds'])),flush=True)
if __name__=='__main__':main()
