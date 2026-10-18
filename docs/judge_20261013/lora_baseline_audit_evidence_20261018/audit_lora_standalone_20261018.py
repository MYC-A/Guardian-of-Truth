"""Independent process baseline audit on frozen rendered requests; no gold."""
import argparse,contextlib,hashlib,json,math,time
from pathlib import Path

def sha(raw):return hashlib.sha256(raw).hexdigest()
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--model',type=Path,required=True);p.add_argument('--adapter',type=Path,required=True);p.add_argument('--requests',type=Path,required=True);p.add_argument('--selection',type=Path,required=True);p.add_argument('--mode',choices=['vanilla','disabled','active'],required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    a.out.mkdir(exist_ok=False);start=time.monotonic()
    import torch
    from transformers import AutoTokenizer,AutoModelForCausalLM
    torch.set_num_threads(6);torch.manual_seed(20261018);torch.backends.cuda.matmul.allow_tf32=True
    tok=AutoTokenizer.from_pretrained(a.model,local_files_only=True,trust_remote_code=False)
    pick=json.loads(a.selection.read_bytes());wanted={(r['dataset'],r['key']):r for r in pick['rows']};plans=[]
    for line in a.requests.read_bytes().splitlines():
        r=json.loads(line);key=(r['dataset'],r['key'])
        if key not in wanted:continue
        assert r['input_sha256']==wanted[key]['input_sha256']==sha(r['text'].encode('utf-8','surrogatepass'))
        ids=tok.encode(r['text'],add_special_tokens=False)
        assert sha(json.dumps(ids,separators=(',',':')).encode())==r['input_token_sha256'] or sha(json.dumps(ids).encode())==r['input_token_sha256'],'TOKEN_IDENTITY'
        plans.append(dict(r,ids=ids))
    assert len(plans)==len(wanted)==78
    # Resolve aliases here independently rather than importing production scoring.
    aliases={'yes':('YES','Yes','yes',' YES',' Yes',' yes'),'no':('NO','No','no',' NO',' No',' no')}
    groups={name:sorted({e[0] for s in words if len(e:=tok.encode(s,add_special_tokens=False))==1}) for name,words in aliases.items()}
    assert groups['yes'] and groups['no'] and not set(groups['yes'])&set(groups['no'])
    model=AutoModelForCausalLM.from_pretrained(a.model,local_files_only=True,trust_remote_code=False,dtype=torch.bfloat16,attn_implementation='sdpa').to('cuda')
    if a.mode!='vanilla':
        from peft import PeftModel
        model=PeftModel.from_pretrained(model,a.adapter,is_trainable=False)
    model.eval();model.config.use_cache=False
    yi=torch.tensor(groups['yes'],device='cuda');ni=torch.tensor(groups['no'],device='cuda')
    state={}
    with (model.disable_adapter() if a.mode=='disabled' else contextlib.nullcontext()),torch.inference_mode():
        if a.mode!='vanilla':
            status=model.get_layer_status();state=dict(layers=len(status),enabled=sum(s.enabled for s in status),merged=sum(bool(s.merged_adapters) for s in status))
            assert state['merged']==0
            assert state['enabled']==(0 if a.mode=='disabled' else state['layers'])
        else:
            assert not any('lora_' in n for n,_ in model.named_parameters()),'VANILLA_CONTAINS_ADAPTER'
        with (a.out/'scores.jsonl').open('w',encoding='utf-8',buffering=1) as f:
            for i,r in enumerate(plans):
                x=torch.tensor([r['ids']],device='cuda');logits=model(input_ids=x,use_cache=False,logits_to_keep=1).logits[0,-1,:].float()
                # Also calculate full-vocabulary log-softmax route independently.
                lp=logits.log_softmax(0)
                score=float(torch.logsumexp(logits[yi],0)-torch.logsumexp(logits[ni],0))
                alternate=float(torch.logsumexp(lp[yi],0)-torch.logsumexp(lp[ni],0));assert math.isfinite(score) and abs(score-alternate)<.0001
                rec={k:r[k] for k in ('dataset','key','id','input_sha256','input_token_sha256','row_sha256')}
                rec.update(mode=a.mode,score=score,log_softmax_score=alternate,yes_logits=logits[yi].tolist(),no_logits=logits[ni].tolist(),
                           canonical_yes_logit=float(logits[tok.encode('YES',add_special_tokens=False)[0]]),canonical_no_logit=float(logits[tok.encode('NO',add_special_tokens=False)[0]]))
                f.write(json.dumps(rec)+'\n')
                if (i+1)%20==0:print(json.dumps(dict(mode=a.mode,done=i+1,total=len(plans))),flush=True)
    out=dict(complete=True,mode=a.mode,rows=len(plans),labels_loaded=False,training_steps_added=0,
        base_weights_sha256={p.name:sha(p.read_bytes()) for p in a.model.glob('*.safetensors')},
        adapter_sha256=sha((a.adapter/'adapter_model.safetensors').read_bytes()) if a.mode!='vanilla' else None,
        adapter_state=state,answer_ids=groups,script_sha256=sha(Path(__file__).read_bytes()),selection_sha256=sha(a.selection.read_bytes()),
        elapsed=time.monotonic()-start)
    (a.out/'DONE.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out),flush=True)
if __name__=='__main__':main()
