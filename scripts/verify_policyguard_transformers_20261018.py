"""Bounded, label-blind cross-engine check of first eight frozen native inputs."""
import argparse
import json
from pathlib import Path
import time


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model',type=Path,required=True)
    p.add_argument('--inputs',type=Path,required=True)
    p.add_argument('--vllm-run',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    assert not a.out.exists()
    import torch
    from transformers import AutoTokenizer,AutoModelForCausalLM
    start=time.monotonic()
    tokenizer=AutoTokenizer.from_pretrained(a.model,local_files_only=True,trust_remote_code=False)
    model=AutoModelForCausalLM.from_pretrained(a.model,local_files_only=True,trust_remote_code=False,
            dtype=torch.bfloat16,attn_implementation='sdpa').to('cuda').eval()
    raw=[json.loads(l) for l in a.inputs.read_text(encoding='utf-8').splitlines()][:8]
    old=[json.loads(l) for l in (a.vllm_run/'predictions.jsonl').read_text(encoding='utf-8').splitlines()][:8]
    outputs=[]
    for r,prior in zip(raw,old):
        assert r['id']==prior['id']
        prompt=r['policy_and_trajectory']+'\n\nOutput violation or no_violation.'
        inputs=tokenizer(prompt,return_tensors='pt',add_special_tokens=False).to('cuda')
        with torch.inference_mode():
            generated=model.generate(**inputs,max_new_tokens=4,do_sample=False,
                                     temperature=None,top_p=None,top_k=None,use_cache=True)
        ids=generated[0,inputs['input_ids'].shape[1]:].tolist()
        outputs.append(dict(id=r['id'],token_ids=ids,raw=tokenizer.decode(ids,skip_special_tokens=True),
                            vllm_token_ids=prior['output_token_ids'],exact_match=ids==prior['output_token_ids']))
    result=dict(engine='transformers',rows=8,labels_loaded=False,greedy=True,use_cache=True,
                torch=torch.__version__,elapsed=time.monotonic()-start,
                exact_token_matches=sum(r['exact_match'] for r in outputs),outputs=outputs)
    a.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
