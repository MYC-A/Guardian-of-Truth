"""Finite 90-minute warm start; original adapter/base are read-only."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import sys
import time
import traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src'),str(ROOT/'scripts')]
from scripts.v5_35b_common import BASE_REVISION, awq_loader_compat, read, sha, target_names, target_suffixes, verify_model, write
from scripts.v5_35b_resume import admit_speed_probe
from scripts.v6_verifier_data import OLD_ADAPTER_SHA, SEED


def run(a):
    a.out.mkdir(exist_ok=False); started=time.monotonic()
    try:
        if a.budget_seconds != 5400: raise ValueError('UNREGISTERED_BUDGET')
        source=json.loads((a.source/'TRAINED.json').read_bytes())
        adapter=a.source/'adapter'
        if not source['epoch_complete'] or source['rows_done']!=1458 or source['adapter_sha256']!=OLD_ADAPTER_SHA or sha(adapter/'adapter_model.safetensors')!=OLD_ADAPTER_SHA:
            raise ValueError('SOURCE_ADAPTER_DRIFT')
        prepared=json.loads((a.data/'DONE.json').read_bytes())
        if not prepared['complete'] or prepared['base_revision']!=BASE_REVISION or prepared['rows']!=128 or sha(a.data/'train_tokens.jsonl')!=prepared['train_tokens_sha256']:
            raise ValueError('DATA_DRIFT')
        records=read(a.data/'train_tokens.jsonl')
        if len(records)!=128 or any(records[i]['pair_id']!=records[i+1]['pair_id'] or {records[i]['label'],records[i+1]['label']}!={0,1} for i in range(0,128,2)):
            raise ValueError('TRAIN_PAIR_DRIFT')
        verify_model(a.model,a.manifest)
        meta=dict(source_adapter_sha256=OLD_ADAPTER_SHA,base_revision=BASE_REVISION,
            data_sha256=prepared['train_tokens_sha256'],source_sha256=sha(Path(__file__)),
            seed=SEED,learning_rate=5e-6,rank=16,alpha=32,dropout=.05,effective_batch=8,
            objective='BCE exact violation YES versus NO, whole-turn verifier prompt',
            fresh_initialization=False,optimizer_reset=True,new_task_not_old_epoch_resume=True,
            budget_seconds=a.budget_seconds,rows_total=128,human_reviewed=False,
            status='EXPLORATORY_ONLY_HUMAN_UNVERIFIED',automatic_promotion=False)
        write(a.out/'START.json',meta)
        import torch
        from peft import LoraConfig,get_peft_model,set_peft_model_state_dict
        from safetensors.torch import load_file
        from gptqmodel import GPTQModel,BACKEND
        from gptqmodel.nn_modules.qlinear import torch_awq
        torch.set_num_threads(6);torch.manual_seed(SEED)
        torch.backends.cuda.matmul.allow_tf32=True
        with awq_loader_compat(a.model,a.out/'LOADER_COMPATIBILITY.json'):
            base=GPTQModel.load(str(a.model),device='cuda:0',backend=BACKEND.AWQ_TORCH,dtype=torch.bfloat16,
                trust_remote_code=False,local_files_only=True,attn_implementation='sdpa').model
        for parameter in base.parameters():parameter.requires_grad_(False)
        base.config.use_cache=False;base.config.text_config.use_cache=False
        base.config.text_config.output_router_logits=False
        targets=target_names([n for n,m in base.named_modules() if isinstance(m,torch.nn.Linear)],8,True)
        model=get_peft_model(base,LoraConfig(task_type='CAUSAL_LM',r=16,lora_alpha=32,lora_dropout=.05,
            target_modules=target_suffixes(True),layers_to_transform=list(range(32,40)),layers_pattern='layers',bias='none'))
        injected=sorted(n.removeprefix('base_model.model.') for n,m in model.named_modules() if hasattr(m,'lora_A') and len(m.lora_A))
        if len(targets)!=50 or injected!=targets:raise ValueError('TARGET_SET_DRIFT')
        weights=load_file(adapter/'adapter_model.safetensors')
        loaded=set_peft_model_state_dict(model,weights)
        if loaded.unexpected_keys or any('lora_' in n for n in loaded.missing_keys):raise ValueError('INCOMPLETE_WARM_START')
        # Export once before any update to prove all imported adapter tensors match.
        model.save_pretrained(a.out/'initial-adapter',safe_serialization=True)
        initial=load_file(a.out/'initial-adapter/adapter_model.safetensors')
        if set(initial)!=set(weights) or any(not torch.equal(initial[k],weights[k]) for k in weights):raise ValueError('INITIAL_ADAPTER_VALUES_DIFFER')
        del initial,weights
        trainable=[(n,p) for n,p in model.named_parameters() if p.requires_grad]
        if len(trainable)!=100 or any('lora_' not in n or p.device.type!='cuda' for n,p in trainable):raise ValueError('TRAINABLE_BOUNDARY')
        parameters=[p for _,p in trainable]
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant':False})
        underlying=model.get_base_model()
        if hasattr(underlying,'_require_grads_hook'):underlying.disable_input_require_grads()
        model.train()
        optimizer=torch.optim.AdamW(parameters,lr=5e-6,weight_decay=.01,fused=True)
        yi=torch.tensor(prepared['answer_ids']['yes'],device='cuda');ni=torch.tensor(prepared['answer_ids']['no'],device='cuda')
        def odds(r):
            ids=torch.tensor([r['ids']],device='cuda')
            with torch.autocast('cuda',dtype=torch.bfloat16):
                logits=model(input_ids=ids,attention_mask=torch.ones_like(ids),mm_token_type_ids=torch.zeros_like(ids),use_cache=False,logits_to_keep=1).logits[0,-1].float()
            return torch.logsumexp(logits[yi],0)-torch.logsumexp(logits[ni],0)
        # Same admitted optimization as V5; recheck weight parity and model gradients.
        original=torch_awq.dequantize_gemm; compiled=torch.compile(original,fullgraph=True,dynamic=False)
        shapes=set();warm=[]
        for name,module in base.named_modules():
            if not isinstance(module,torch_awq.AwqTorchLinear):continue
            key=(tuple(module.qweight.shape),tuple(module.scales.shape))
            if key in shapes:continue
            shapes.add(key)
            kwargs=dict(qweight=module.qweight,qzeros=module.qzeros,scales=module.scales,bits=4,group_size=32)
            with torch.autocast('cuda',dtype=torch.bfloat16):
                ref=original(**kwargs);fast=compiled(**kwargs)
            if not torch.equal(ref,fast):raise ValueError('DEQUANT_WEIGHT_PARITY')
            warm.append(dict(name=name,bit_exact=True))
        del ref,fast
        probe=min(records,key=lambda r:(r['tokens'],r['id']))
        cpu_rng=torch.get_rng_state();cuda_rng=torch.cuda.get_rng_state_all();arms=[]
        for fn in (original,original,compiled):
            torch_awq.dequantize_gemm=fn;torch.set_rng_state(cpu_rng);torch.cuda.set_rng_state_all(cuda_rng)
            optimizer.zero_grad(set_to_none=True);timer=time.monotonic()
            score=odds(probe);loss=torch.nn.functional.binary_cross_entropy_with_logits(score,score.new_tensor(float(probe['label'])))
            loss.backward();torch.cuda.synchronize()
            if any(p.grad is None or not bool(torch.isfinite(p.grad).all()) for p in parameters):raise ValueError('PROBE_GRADIENT')
            arms.append((float(score.detach()),float(loss.detach()),[p.grad.detach().clone() for p in parameters],
                time.monotonic()-timer,hashlib.sha256(torch.cuda.get_rng_state().cpu().numpy().tobytes()).hexdigest()))
        def compare(left,right):
            diffs=[float((x-y).abs().max()) for x,y in zip(left[2],right[2])]
            d2=[float((x.float()-y.float()).square().sum()) for x,y in zip(left[2],right[2])]
            n2=[float(x.float().square().sum()) for x in left[2]]
            return dict(score_abs_delta=abs(left[0]-right[0]),loss_abs_delta=abs(left[1]-right[1]),
                gradient_relative_l2=math.sqrt(sum(d2)/max(sum(n2),1e-30)),
                worst_tensor_gradient_relative_l2=max(math.sqrt(d/max(n,1e-30)) for d,n in zip(d2,n2)),
                max_gradient_abs_delta=max(diffs),post_dropout_rng_equal=left[4]==right[4])
        comparison=dict(baseline_repeat_control=compare(arms[0],arms[1]),compiled_comparison=compare(arms[0],arms[2]))
        admitted=admit_speed_probe(comparison)
        write(a.out/'TECHNICAL_GATE.json',dict(complete=True,initial_tensors_exact=True,source_modules=50,tensors=100,
            compiled_accepted=admitted,weight_parity=warm,gradient_probe=comparison,optimizer_updates=0,
            relative_noise_gate_not_absolute_equivalence=True,probe_id=probe['id']))
        torch_awq.dequantize_gemm=compiled if admitted else original
        torch.set_rng_state(cpu_rng);torch.cuda.set_rng_state_all(cuda_rng)
        del arms;optimizer.zero_grad(set_to_none=True)
        # One complete pair stays together within each update. No quality ordering.
        import random
        pairs=list(range(64));random.Random(SEED).shuffle(pairs)
        order=[i for p in pairs for i in (2*p,2*p+1)]
        rows_done=steps=forwarded=0;training_started=time.monotonic();stopped=False
        def stop(_sig,_frame):
            nonlocal stopped
            stopped=True
        signal.signal(signal.SIGTERM,stop)
        meta.update(compiled_awq_dequant=admitted,target_modules=targets,
            trainable_parameters=sum(p.numel() for p in parameters),model_ready_seconds=time.monotonic()-started)
        write(a.out/'MODEL_READY.json',meta)
        def checkpoint(name):
            folder=a.out/name;folder.mkdir(exist_ok=False)
            model.save_pretrained(folder/'adapter',safe_serialization=True)
            torch.save(dict(optimizer=optimizer.state_dict(),cpu_rng=torch.get_rng_state(),cuda_rng=torch.cuda.get_rng_state_all(),
                order=order,rows_done=rows_done,steps=steps),folder/'state.pt')
            write(folder/'CHECKPOINT.json',dict(meta,steps=steps,rows_done=rows_done,
                adapter_sha256=sha(folder/'adapter/adapter_model.safetensors')))
        with (a.out/'training.jsonl').open('w',buffering=1) as log:
            for offset in range(0,len(order),8):
                if stopped or time.monotonic()-training_started>=a.budget_seconds:break
                batch=order[offset:offset+8];losses=[];optimizer.zero_grad(set_to_none=True)
                for index in batch:
                    if stopped or time.monotonic()-training_started>=a.budget_seconds:break
                    record=records[index]
                    write(a.out/'CURRENT_ROW.json',dict(id=record['id'],tokens=record['tokens'],committed_rows=rows_done,
                        completed_rows_in_batch=len(losses),steps=steps,training_seconds=time.monotonic()-training_started))
                    score=odds(record);loss=torch.nn.functional.binary_cross_entropy_with_logits(score,score.new_tensor(float(record['label'])))
                    if not bool(torch.isfinite(loss)):raise ValueError('NONFINITE_LOSS')
                    (loss/len(batch)).backward();losses.append(float(loss.detach()));forwarded+=1
                if len(losses)!=len(batch):optimizer.zero_grad(set_to_none=True);break
                norm=float(torch.nn.utils.clip_grad_norm_(parameters,1.0))
                if not math.isfinite(norm):raise ValueError('NONFINITE_GRADIENT')
                for group in optimizer.param_groups:group['lr']=5e-6*min(1,(steps+1)/2)
                optimizer.step();steps+=1;rows_done+=len(batch)
                checkpoint('checkpoint-%03d'%steps)
                item=dict(steps=steps,rows_done=rows_done,rows_total=128,loss=sum(losses)/len(losses),grad_norm=norm,
                    training_seconds=time.monotonic()-training_started,
                    estimated_remaining_seconds=(time.monotonic()-training_started)/rows_done*(128-rows_done))
                log.write(json.dumps(item)+'\n');write(a.out/'PROGRESS.json',item);print(json.dumps(item),flush=True)
        checkpoint('final');model.save_pretrained(a.out/'adapter',safe_serialization=True)
        new_sha=sha(a.out/'adapter/adapter_model.safetensors')
        if steps<=0 or new_sha==OLD_ADAPTER_SHA:raise ValueError('NO_COMMITTED_ADAPTER_UPDATE')
        if sha(adapter/'adapter_model.safetensors')!=OLD_ADAPTER_SHA:raise ValueError('SOURCE_ADAPTER_WAS_CHANGED')
        write(a.out/'TRAINED.json',dict(meta,complete=True,optimizer_updates=steps,rows_done=rows_done,
            rows_forwarded=forwarded,epoch_complete=rows_done==128,epoch_fraction=rows_done/128,
            adapter_sha256=new_sha,training_seconds=time.monotonic()-training_started,
            elapsed_seconds=time.monotonic()-started,budget_exhausted=rows_done<128,
            source_adapter_unchanged=True))
    except Exception as e:
        write(a.out/'FAIL.json',dict(complete=False,error=str(e),traceback=traceback.format_exc(),seconds=time.monotonic()-started))
        raise


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for n in ('model','manifest','source','data','out'):p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--budget-seconds',type=int,default=5400)
    run(p.parse_args())
