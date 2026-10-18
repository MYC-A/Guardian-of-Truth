"""Bounded Transformers contract audit. Frozen settings; inference never reads gold.

Compare full native300 under raw greedy4, raw card defaults4, raw greedy16,
and chat greedy16. These are diagnostic formats, not a search for a dev winner.
Independently recompute both full label likelihoods on fixed first4 dev inputs.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from scripts.eval_policyguard_20261018 import load_requests,parse_label


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    assert not a.out.exists()
    a.out.mkdir()
    root=a.root; modelpath=root/'models/policyguard-4b'
    native=load_requests(root/'data/guardian-judge-eval-data-v1/auxiliary_policyguard/trajectories.jsonl','native',0)
    dev=load_requests(root/'data/guardian-judge-eval-data-v1/compli_dev/inputs.csv','transfer',4)
    old=[json.loads(l) for l in (root/'runs/policyguard-dev520/predictions.jsonl').read_text().splitlines()][:4]
    import torch
    from transformers import AutoTokenizer,AutoModelForCausalLM
    torch.manual_seed(20261018)
    start=time.monotonic()
    t=AutoTokenizer.from_pretrained(modelpath,local_files_only=True,trust_remote_code=False,padding_side='left')
    model=AutoModelForCausalLM.from_pretrained(modelpath,local_files_only=True,trust_remote_code=False,
                dtype=torch.bfloat16,attn_implementation='sdpa').to('cuda').eval()
    score_check=[]
    for row,previous in zip(dev,old):
        assert row['id']==previous['id']
        assert hashlib.sha256(row['prompt'].encode()).hexdigest()==previous['prompt_sha256']
        prefix=row['prompt']+'\n'; pt=t.encode(prefix,add_special_tokens=False)
        for label in ('violation','no_violation'):
            full=t.encode(prefix+label,add_special_tokens=False)
            assert full[:len(pt)]==pt
            suffix=full[len(pt):]; m=len(suffix)
            ids=torch.tensor([full],device='cuda')
            with torch.inference_mode():
                logits=model(input_ids=ids,attention_mask=torch.ones_like(ids),
                             use_cache=False,logits_to_keep=m+1).logits[0,:m].float()
                lp=logits.log_softmax(-1).gather(-1,torch.tensor(suffix,device='cuda')[:,None]).flatten().tolist()
            prior=previous['label_scores'][label]
            assert prior['token_ids']==suffix
            score_check.append(dict(id=row['id'],label=label,token_ids=suffix,
                prefix_last_token=pt[-1],first_label_token=suffix[0],
                tf_token_logprobs=lp,tf_logprob=sum(lp),vllm_logprob=prior['logprob'],
                difference=sum(lp)-prior['logprob']))
    (a.out/'FULL_LABEL_CHECK.json').write_text(json.dumps(dict(rows=4,full_label_checks=8,
        labels_loaded=False,sign='violation minus no_violation',
        records=score_check),indent=2)+'\n')
    settings=[('raw_greedy4',False,4,False),('raw_card_defaults4',False,4,True),
              ('raw_greedy16',False,16,False),('chat_greedy16',True,16,False)]
    summary=[]
    for name,chat,budget,sample in settings:
        arm_start=time.monotonic()
        with (a.out/(name+'.jsonl')).open('w',encoding='utf-8') as stream:
            for pos in range(0,len(native),16):
                batch=native[pos:pos+16]
                prompts=[t.apply_chat_template([dict(role='user',content=r['prompt'])],tokenize=False,
                          add_generation_prompt=True) if chat else r['prompt'] for r in batch]
                inputs=t(prompts,return_tensors='pt',padding=True,add_special_tokens=False).to('cuda')
                options=dict(max_new_tokens=budget,use_cache=True,do_sample=sample)
                if not sample: options.update(temperature=None,top_p=None,top_k=None)
                with torch.inference_mode(): generated=model.generate(**inputs,**options)
                for r,prompt,ids in zip(batch,prompts,generated[:,inputs['input_ids'].shape[1]:]):
                    raw=t.decode(ids,skip_special_tokens=True)
                    stream.write(json.dumps(dict(id=r['id'],position=r['position'],
                        raw=raw,token_ids=ids.tolist(),strict_label=parse_label(raw),
                        author_substring_label=0 if 'no_violation' in raw.lower() else 1,
                        prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest()),ensure_ascii=True)+'\n')
                stream.flush()
                print(json.dumps(dict(event='progress',arm=name,done=pos+len(batch),total=len(native))),flush=True)
        summary.append(dict(arm=name,chat_template=chat,max_tokens=budget,do_sample=sample,
                            rows=len(native),seconds=time.monotonic()-arm_start))
    done=dict(complete=True,labels_loaded=False,settings=summary,
              elapsed=time.monotonic()-start,torch=torch.__version__,
              script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              note='300 frozen native examples, not full12000/paper reproduction; no dev prompt chosen.')
    (a.out/'DONE.json').write_text(json.dumps(done,indent=2)+'\n')
    print(json.dumps(done),flush=True)


if __name__=='__main__': main()
