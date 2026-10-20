"""Bounded source-rationale SFT plus a small frozen-TRAIN BCE replay."""
import argparse
import json
import math
import os
from pathlib import Path
import random
import signal
import sys
import time
import traceback
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src'),str(ROOT/'scripts')]
from scripts.v5_35b_common import BASE_REVISION,awq_loader_compat,read,sha,target_names,target_suffixes,verify_model,write
from scripts.v6_verifier_data import OLD_ADAPTER_SHA,SEED

def answer_slice(total,prompt,answer):
    if total!=prompt+answer or prompt<1 or answer<1:raise ValueError('INVALID_SFT_ALIGNMENT')
    return slice(prompt-1,total-1)

def validate_resume(receipt,state,data_sha,layers,order):
    if receipt['data_sha256']!=data_sha or receipt['base_revision']!=BASE_REVISION or receipt['layers']!=layers:
        raise ValueError('RESUME_DATA_MODEL_PROFILE_DRIFT')
    if state['order']!=order or state['rows_done']!=receipt['rows_done'] or state['steps']!=receipt['steps']:
        raise ValueError('RESUME_ORDER_OR_PROGRESS_DRIFT')
    if state['rows_done']!=8*state['steps'] or not 0<state['rows_done']<=len(order):
        raise ValueError('RESUME_NOT_COMMITTED_BATCH_BOUNDARY')


def validate_recipe(records,meta,native=False):
    sft=sum(r['objective']=='sft' for r in records);bce=sum(r['objective']=='bce' for r in records)
    if not native:
        if len(records)!=224 or sft!=192:raise ValueError('FROZEN_TRAIN_COUNT')
        return
    if (meta.get('recipe')!='V15_NATIVE_RATIONALE_V1' or sft!=meta.get('sft_rows') or
            bce!=32 or len(records)!=sft+32 or not 80<=sft<=144 or sft%8 or
            len({r['id'] for r in records})!=len(records)):
        raise ValueError('FROZEN_NATIVE_RECIPE')
    groups={}
    for r in records:
        if r['objective']=='sft':groups.setdefault(r['pair_id'],[]).append(r['label'])
    if any(sorted(v)!=[0,1] for v in groups.values()):raise ValueError('NATIVE_RECIPE_NOT_COMPLETE_PAIRS')

def run(a):
    a.out.mkdir(exist_ok=False);started=time.monotonic();steps=0
    try:
        meta=json.loads((a.data/'DONE.json').read_bytes())
        if not meta['complete'] or sha(a.data/'train_tokens.jsonl')!=meta['train_tokens_sha256']:raise ValueError('TRAIN_DATA_DRIFT')
        records=read(a.data/'train_tokens.jsonl')
        native=getattr(a,'native_recipe',False);validate_recipe(records,meta,native)
        source=a.lab/'v5-35b-20261019/train-recovered-v1/adapter'
        if sha(source/'adapter_model.safetensors')!=OLD_ADAPTER_SHA:raise ValueError('SOURCE_ADAPTER_DRIFT')
        modelpath=a.lab/'models/qwen36-awq';verify_model(modelpath,a.lab/'v5-35b-20261019/BASE_MODEL_MANIFEST.json')
        start=dict(base_revision=BASE_REVISION,source_adapter_sha256=OLD_ADAPTER_SHA,
            data_sha256=meta['train_tokens_sha256'],source_sha256=sha(Path(__file__)),
            seed=SEED,learning_rate=2e-5,rank=16,alpha=32,dropout=.05,layers=a.layers,
            effective_batch=8,rows_total=len(records),objective=str(sum(r['objective']=='sft' for r in records))+' source-rationale SFT +32 original TRAIN verifier BCE; equal row weight',
            recipe=meta.get('recipe','V7_ABSTRACT_WORKFLOW_V1'),
            optimizer_reset=True,deadline_unix=a.deadline,human_reviewed=False,
            status='EXPLORATORY_ONLY_HUMAN_UNVERIFIED',automatic_promotion=False)
        write(a.out/'START.json',start)
        import torch
        from peft import LoraConfig,get_peft_model,set_peft_model_state_dict
        from safetensors.torch import load_file
        from gptqmodel import GPTQModel,BACKEND
        torch.set_num_threads(6);torch.manual_seed(SEED);torch.backends.cuda.matmul.allow_tf32=True
        with awq_loader_compat(modelpath,a.out/'LOADER_COMPATIBILITY.json'):
            base=GPTQModel.load(str(modelpath),device='cuda:0',backend=BACKEND.AWQ_TORCH,dtype=torch.bfloat16,
                trust_remote_code=False,local_files_only=True,attn_implementation='sdpa').model
        for p in base.parameters():p.requires_grad_(False)
        base.config.use_cache=False;base.config.text_config.use_cache=False;base.config.text_config.output_router_logits=False
        targets=target_names([n for n,m in base.named_modules() if isinstance(m,torch.nn.Linear)],a.layers,True)
        model=get_peft_model(base,LoraConfig(task_type='CAUSAL_LM',r=16,lora_alpha=32,lora_dropout=.05,
            target_modules=target_suffixes(True),layers_to_transform=list(range(40-a.layers,40)),layers_pattern='layers',bias='none'))
        injected=sorted(n.removeprefix('base_model.model.') for n,m in model.named_modules() if hasattr(m,'lora_A') and len(m.lora_A))
        expected=50*(a.layers//8)
        if len(targets)!=expected or injected!=targets:raise ValueError('TARGET_BOUNDARY')
        weights=load_file(source/'adapter_model.safetensors');loaded=set_peft_model_state_dict(model,weights)
        if loaded.unexpected_keys:raise ValueError('UNEXPECTED_WARMSTART_KEYS')
        model.save_pretrained(a.out/'initial-adapter',safe_serialization=True)
        initial=load_file(a.out/'initial-adapter/adapter_model.safetensors')
        if not set(weights)<=set(initial) or any(not torch.equal(initial[k],weights[k]) for k in weights):raise ValueError('OLD_VALUES_DIFFER')
        newkeys=set(initial)-set(weights)
        if len(newkeys)!=2*expected-100 or any('lora_B.' in k and bool(torch.count_nonzero(initial[k])) for k in newkeys):raise ValueError('NEW_MODULES_NOT_ZERO_DELTA')
        del initial,weights
        resume_state=None;resume_meta=None;prior_training_seconds=0;prior_forwarded=0
        if a.resume is not None:
            resume_meta=json.loads((a.resume/'CHECKPOINT.json').read_bytes())
            if sha(a.resume/'adapter/adapter_model.safetensors')!=resume_meta['adapter_sha256']:raise ValueError('RESUME_ADAPTER_DRIFT')
            restored=load_file(a.resume/'adapter/adapter_model.safetensors')
            loaded=set_peft_model_state_dict(model,restored)
            if loaded.unexpected_keys or any('lora_' in n for n in loaded.missing_keys):raise ValueError('INCOMPLETE_RESUME_ADAPTER')
            model.save_pretrained(a.out/'resume-loaded-adapter',safe_serialization=True)
            checked=load_file(a.out/'resume-loaded-adapter/adapter_model.safetensors')
            if set(checked)!=set(restored) or any(not torch.equal(checked[k],restored[k]) for k in restored):raise ValueError('RESUME_TENSOR_VALUES_DIFFER')
            del checked,restored
            resume_state=torch.load(a.resume/'state.pt',map_location='cpu',weights_only=False)
            previous=a.resume.parent/'TRAINED.json'
            if previous.exists():
                prior=json.loads(previous.read_bytes());prior_training_seconds=prior.get('total_training_seconds',prior['training_seconds']);prior_forwarded=prior['rows_forwarded']
            start.update(optimizer_reset=False,resumed_from=str(a.resume),resume_adapter_sha256=resume_meta['adapter_sha256'],
                prior_training_seconds=prior_training_seconds,prior_committed_rows=resume_state['rows_done'],prior_rows_forwarded=prior_forwarded)
        trainable=[(n,p) for n,p in model.named_parameters() if p.requires_grad]
        if len(trainable)!=2*expected or any('lora_' not in n or p.device.type!='cuda' for n,p in trainable):raise ValueError('TRAINABLE_BOUNDARY')
        parameters=[p for _,p in trainable]
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant':False})
        underlying=model.get_base_model()
        if hasattr(underlying,'_require_grads_hook'):underlying.disable_input_require_grads()
        model.train();optimizer=torch.optim.AdamW(parameters,lr=2e-5,weight_decay=.01,fused=True)
        yi=torch.tensor(meta['answer_ids']['yes'],device='cuda');ni=torch.tensor(meta['answer_ids']['no'],device='cuda')
        def loss_for(r):
            answer=r.get('answer_ids',[]) if r['objective']=='sft' else []
            allids=r['ids']+answer;ids=torch.tensor([allids],device='cuda')
            with torch.autocast('cuda',dtype=torch.bfloat16):
                output=model(input_ids=ids,attention_mask=torch.ones_like(ids),mm_token_type_ids=torch.zeros_like(ids),
                    use_cache=False,logits_to_keep=len(answer)+1).logits[0].float()
            if r['objective']=='sft':
                answer_slice(len(allids),len(r['ids']),len(answer))
                if output.shape[0]!=len(answer)+1:raise ValueError('LOGITS_ANSWER_ALIGNMENT')
                return torch.nn.functional.cross_entropy(output[:-1],torch.tensor(answer,device='cuda'))
            odds=torch.logsumexp(output[-1,yi],0)-torch.logsumexp(output[-1,ni],0)
            return torch.nn.functional.binary_cross_entropy_with_logits(odds,odds.new_tensor(float(r['label'])))
        # Longest input probes memory/backward before any optimizer update; no quality choice.
        probe=max(records,key=lambda r:r['tokens']);timer=time.monotonic();loss=loss_for(probe);loss.backward();torch.cuda.synchronize()
        if not bool(torch.isfinite(loss)) or any(p.grad is None or not bool(torch.isfinite(p.grad).all()) for p in parameters):raise ValueError('TECHNICAL_GRADIENT')
        write(a.out/'TECHNICAL_GATE.json',dict(complete=True,optimizer_updates=resume_state['steps'] if resume_state else 0,segment_optimizer_updates=0,layers=a.layers,
            source_modules=expected,tensors=2*expected,imported_tensors=100,old_tensors_exact=True,
            added_tensors=len(newkeys),new_B_zero=True,probe_tokens=probe['tokens'],probe_seconds=time.monotonic()-timer,
            max_memory_bytes=torch.cuda.max_memory_allocated(),compiled_awq_dequant=False,
            reason='original backend retained after V6 compiled-gradient gate rejected optimization'))
        optimizer.zero_grad(set_to_none=True)
        # Interleave whole pairs from both objectives; no row is chosen from eval performance.
        groups=[records[i:i+2] for i in range(0,len(records),2)];random.Random(SEED).shuffle(groups)
        order=[r for pair in groups for r in pair]
        write(a.out/'ORDER.json',dict(ids=[r['id'] for r in order]))
        start.update(source_modules=expected,trainable_parameters=sum(p.numel() for p in parameters),model_ready_seconds=time.monotonic()-started)
        write(a.out/'MODEL_READY.json',start)
        rows_done=forwarded=0
        if resume_state is not None:
            validate_resume(resume_meta,resume_state,meta['train_tokens_sha256'],a.layers,[r['id'] for r in order])
            optimizer.load_state_dict(resume_state['optimizer'])
            loaded=optimizer.state_dict();saved=resume_state['optimizer']
            if loaded['param_groups']!=saved['param_groups'] or set(loaded['state'])!=set(saved['state']):raise ValueError('RESUME_OPTIMIZER_LAYOUT')
            for key,state in saved['state'].items():
                for field,value in state.items():
                    actual=loaded['state'][key][field]
                    equal=torch.equal(actual.detach().cpu(),value.detach().cpu()) if torch.is_tensor(value) else actual==value
                    if not equal:raise ValueError('RESUME_OPTIMIZER_VALUE:'+field)
            torch.set_rng_state(resume_state['cpu_rng']);torch.cuda.set_rng_state_all(resume_state['cuda_rng'])
            if not torch.equal(torch.get_rng_state(),resume_state['cpu_rng']) or any(not torch.equal(x,y) for x,y in zip(torch.cuda.get_rng_state_all(),resume_state['cuda_rng'])):
                raise ValueError('RESUME_RNG_VALUES_DIFFER')
            rows_done=resume_state['rows_done'];forwarded=prior_forwarded or rows_done;steps=resume_state['steps']
            write(a.out/'RESUME_PROOF.json',dict(complete=True,adapter_tensors_exact=True,optimizer_restored=True,optimizer_values_exact=True,
                cpu_and_cuda_rng_restored=True,order_unchanged=True,rows_done=rows_done,steps=steps,
                state_sha256=sha(a.resume/'state.pt'),checkpoint_sha256=sha(a.resume/'CHECKPOINT.json')))
            del resume_state
        initial_rows=rows_done;training_started=time.monotonic();stopped=False
        def stop(_sig,_frame):
            nonlocal stopped
            stopped=True
        signal.signal(signal.SIGTERM,stop)
        def checkpoint(name):
            folder=a.out/name;folder.mkdir(exist_ok=False);model.save_pretrained(folder/'adapter',safe_serialization=True)
            torch.save(dict(optimizer=optimizer.state_dict(),cpu_rng=torch.get_rng_state(),cuda_rng=torch.cuda.get_rng_state_all(),
                order=[r['id'] for r in order],rows_done=rows_done,steps=steps),folder/'state.pt')
            write(folder/'CHECKPOINT.json',dict(start,steps=steps,rows_done=rows_done,adapter_sha256=sha(folder/'adapter/adapter_model.safetensors')))
        with (a.out/'training.jsonl').open('w',buffering=1) as log:
            for offset in range(rows_done,len(order),8):
                if stopped or time.time()>=a.deadline:break
                batch=order[offset:offset+8];losses=[];optimizer.zero_grad(set_to_none=True)
                for r in batch:
                    if stopped or time.time()>=a.deadline:break
                    write(a.out/'CURRENT_ROW.json',dict(id=r['id'],objective=r['objective'],tokens=r['tokens'],committed_rows=rows_done,
                        completed_rows_in_batch=len(losses),steps=steps,training_seconds=time.monotonic()-training_started))
                    loss=loss_for(r)
                    if not bool(torch.isfinite(loss)):raise ValueError('NONFINITE_LOSS')
                    (loss/len(batch)).backward();losses.append(float(loss.detach()));forwarded+=1
                if len(losses)!=len(batch):optimizer.zero_grad(set_to_none=True);break
                norm=float(torch.nn.utils.clip_grad_norm_(parameters,1))
                if not math.isfinite(norm):raise ValueError('NONFINITE_GRADIENT')
                for g in optimizer.param_groups:g['lr']=2e-5*min(1,(steps+1)/2)
                optimizer.step();steps+=1;rows_done+=len(batch);checkpoint('checkpoint-%03d'%steps)
                item=dict(steps=steps,rows_done=rows_done,rows_total=len(order),loss=sum(losses)/len(losses),grad_norm=norm,
                    training_seconds=time.monotonic()-training_started,
                    estimated_remaining_seconds=(time.monotonic()-training_started)/(rows_done-initial_rows)*(len(order)-rows_done))
                log.write(json.dumps(item)+'\n');write(a.out/'PROGRESS.json',item);print(json.dumps(item),flush=True)
        checkpoint('final');model.save_pretrained(a.out/'adapter',safe_serialization=True)
        if not steps:raise ValueError('NO_COMMITTED_UPDATES')
        if sha(source/'adapter_model.safetensors')!=OLD_ADAPTER_SHA:raise ValueError('SOURCE_CHANGED')
        write(a.out/'TRAINED.json',dict(start,complete=True,optimizer_updates=steps,rows_done=rows_done,rows_forwarded=forwarded,
            epoch_complete=rows_done==len(order),epoch_fraction=rows_done/len(order),adapter_sha256=sha(a.out/'adapter/adapter_model.safetensors'),
            training_seconds=time.monotonic()-training_started,elapsed_seconds=time.monotonic()-started,
            total_training_seconds=prior_training_seconds+time.monotonic()-training_started,
            budget_exhausted=rows_done<len(order),source_adapter_unchanged=True))
        if a.resume is not None and rows_done<len(order):raise ValueError('FULL_PASS_NOT_COMPLETED_WITHIN_DEADLINE')
    except Exception as e:
        write(a.out/'FAIL.json',dict(complete=False,error=str(e),traceback=traceback.format_exc(),optimizer_updates=steps,seconds=time.monotonic()-started));raise

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('lab','data','out'):p.add_argument('--'+k,type=Path,required=True)
    p.add_argument('--deadline',type=float,required=True);p.add_argument('--layers',type=int,choices=[8,16],default=16)
    p.add_argument('--resume',type=Path)
    p.add_argument('--native-recipe',action='store_true')
    run(p.parse_args())
