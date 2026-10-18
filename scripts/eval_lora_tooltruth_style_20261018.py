"""Fixed final adapter vs disabled adapter on style controls; no gold or training."""
import argparse,contextlib,hashlib,json,math,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from guardian_truth.judge.prompting import render
from scripts.judge_stage import answer_ids


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--model',type=Path,required=True)
    p.add_argument('--run',type=Path,required=True);p.add_argument('--input',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True);a=p.parse_args();a.out.mkdir(exist_ok=False);start=time.monotonic()
    import torch
    from transformers import AutoModelForCausalLM,AutoTokenizer
    from peft import PeftModel
    torch.set_num_threads(6);torch.manual_seed(20261018);torch.backends.cuda.matmul.allow_tf32=True
    trained=json.loads((a.run/'TRAINED.json').read_bytes());adapter=a.run/'adapter'
    digest=hashlib.sha256((adapter/'adapter_model.safetensors').read_bytes()).hexdigest();assert digest==trained['adapter_sha256']
    tok=AutoTokenizer.from_pretrained(a.model,local_files_only=True,trust_remote_code=False);yes,no=answer_ids(tok)
    plans=[]
    for line in a.input.read_bytes().splitlines():
        r=json.loads(line);assert 'label' not in r and 'oracle' not in r
        text=render(tok,r['prompt'],r['response'],[]);ids=tok.encode(text,add_special_tokens=False);assert len(ids)<=16384
        plans.append(dict(id=r['id'],text=text,ids=ids,input_sha256=hashlib.sha256(text.encode('utf8','surrogatepass')).hexdigest()))
    assert len(plans)==72
    (a.out/'requests.jsonl').write_bytes(b''.join((json.dumps({k:v for k,v in r.items() if k!='ids'},ensure_ascii=True)+'\n').encode() for r in plans))
    model=AutoModelForCausalLM.from_pretrained(a.model,local_files_only=True,trust_remote_code=False,dtype=torch.bfloat16,attn_implementation='sdpa').to('cuda')
    model=PeftModel.from_pretrained(model,adapter,is_trainable=False);model.eval();model.config.use_cache=False
    yi=torch.tensor(sorted(yes),device='cuda');ni=torch.tensor(sorted(no),device='cuda')
    with (a.out/'scores.jsonl').open('w',encoding='utf8',buffering=1) as f:
        for arm in ('base','adapter'):
            with (model.disable_adapter() if arm=='base' else contextlib.nullcontext()),torch.inference_mode():
                for r in plans:
                    logits=model(input_ids=torch.tensor([r['ids']],device='cuda'),use_cache=False,logits_to_keep=1).logits[0,-1,:].float()
                    score=float(torch.logsumexp(logits[yi],0)-torch.logsumexp(logits[ni],0));assert math.isfinite(score)
                    f.write(json.dumps(dict(id=r['id'],arm=arm,score=score,exact=True,input_sha256=r['input_sha256']))+'\n')
            print(json.dumps(dict(arm=arm,rows=72,seconds=time.monotonic()-start)),flush=True)
    done=dict(complete=True,rows=144,training_steps_added=0,evaluation_gold_loaded=False,adapter_sha256=digest,
        input_sha256=hashlib.sha256(a.input.read_bytes()).hexdigest(),wall_seconds=time.monotonic()-start)
    (a.out/'DONE.json').write_bytes((json.dumps(done,indent=2)+'\n').encode());print(json.dumps(done),flush=True)


if __name__=='__main__':main()
