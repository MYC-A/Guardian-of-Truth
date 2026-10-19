"""Resume the frozen V5 recipe, admitting only bit-exact dequant compilation."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import random
import signal
import sys
import time
import traceback

sys.path[:0] = [str(Path(__file__).resolve().parent)]
from v5_35b_common import BASE_REVISION, awq_loader_compat, read, sha, target_names, target_suffixes, verify_model, write
from v5_35b_train import check_gate


def admit_speed_probe(probe):
    """Fixed exploratory numeric bounds; no label/quality-dependent thresholds."""
    control=probe['baseline_repeat_control']; treatment=probe['compiled_comparison']
    return (treatment['post_dropout_rng_equal'] and control['post_dropout_rng_equal'] and
        treatment['score_abs_delta'] <= 1e-5 and control['score_abs_delta'] <= 1e-5 and
        treatment['loss_abs_delta'] <= 1e-5 and control['loss_abs_delta'] <= 1e-5 and
        treatment['gradient_relative_l2'] <= min(.005, 2*control['gradient_relative_l2']+1e-7) and
        treatment['worst_tensor_gradient_relative_l2'] <= .02 and
        treatment['max_gradient_abs_delta'] <= 2*control['max_gradient_abs_delta']+1e-7)


def interrupted_resume_source(checkpoint, record_path, meta):
    """Authenticate interruption recovery without inventing a TRAINED receipt."""
    rec=json.loads(Path(record_path).read_bytes());checkpoint=Path(checkpoint)
    if (rec.get('kind')!='INTERRUPTED_VERIFIED_CHECKPOINT' or rec.get('complete') is not False or
        not rec.get('checkpoint_complete') or Path(rec['source_checkpoint']).resolve()!=checkpoint.resolve()):
        raise ValueError('INVALID_INTERRUPTION_RECOVERY_RECORD')
    if (rec['adapter_sha256']!=meta['adapter_sha256'] or rec['state_sha256']!=sha(checkpoint/'state.pt') or
        rec['training_log_sha256']!=sha(checkpoint.parent/'training.jsonl')):
        raise ValueError('INTERRUPTED_CHECKPOINT_OR_LOG_DRIFT')
    gate_path=checkpoint.parent/'SPEED_GATE.json'
    if (meta.get('compiled_awq_dequant') is not True or sha(gate_path)!=meta.get('speed_gate_sha256') or
        not json.loads(gate_path.read_bytes()).get('compiled_accepted')):
        raise ValueError('INTERRUPTED_NUMERIC_ADMISSION_DRIFT')
    logs=read(checkpoint.parent/'training.jsonl');last=logs[-1]
    matching=[x for x in logs if x['step']==meta['steps']]
    if (not matching or matching[-1]['rows_done']!=meta['rows_done'] or last!=rec['latest_logged_progress'] or
        rec['steps']!=meta['steps'] or rec['rows_done']!=meta['rows_done'] or
        rec['interrupted_batch_allowance_seconds']!=600 or
        rec['accounted_training_seconds']!=last['seconds']+600):
        raise ValueError('INTERRUPTION_POSITION_OR_TIME_DRIFT')
    return dict(adapter_sha256=rec['adapter_sha256'],rows_done=rec['rows_done'],epoch_complete=False,
        training_seconds=rec['accounted_training_seconds'])


def validate_resume(meta, data, state, gate_sha):
    if (meta['base_revision'] != BASE_REVISION or meta['gate_sha256'] != gate_sha or
            meta['train_tokens_sha256'] != data['train_tokens_sha256']):
        raise ValueError('RESUME_MODEL_DATA_OR_GATE_DRIFT')
    if (meta['layers'], meta['shared'], meta['backend'], meta['rank'], meta['alpha'],
            meta['dropout'], meta['learning_rate'], meta['effective_batch']) != (8, True, 'AWQ_TORCH', 16, 32, .05, 2e-5, 16):
        raise ValueError('RESUME_RECIPE_DRIFT')
    order = list(range(1458)); random.Random(20261019).shuffle(order)
    if state['order'] != order or state['rows_done'] != meta['rows_done'] or state['steps'] != meta['steps']:
        raise ValueError('RESUME_POSITION_OR_ORDER_DRIFT')
    if not 0 < state['rows_done'] < 1458 or state['rows_done'] != 16 * state['steps']:
        raise ValueError('RESUME_NOT_AT_COMMITTED_BATCH_BOUNDARY')
    if len(state['optimizer']['state']) != 100:
        raise ValueError('RESUME_OPTIMIZER_STATE_MISSING')
    for value in state['optimizer']['state'].values():
        if int(value['step']) != state['steps']:
            raise ValueError('RESUME_OPTIMIZER_STEP_DRIFT')


def main():
    p = argparse.ArgumentParser()
    for n in ('model', 'manifest', 'data', 'gate', 'resume', 'out', 'benchmark'):
        p.add_argument('--' + n, type=Path, required=True)
    p.add_argument('--total-budget-seconds', type=int, default=32400)
    p.add_argument('--recovery-record',type=Path)
    a = p.parse_args(); a.out.mkdir(exist_ok=False)
    started = time.monotonic()
    try:
        if a.total_budget_seconds not in (32400, 57600):
            raise ValueError('UNREGISTERED_TOTAL_TIME_BUDGET')
        cache=(a.resume.parent/'compile-cache') if a.recovery_record else (a.out/'compile-cache')
        os.environ['TORCHINDUCTOR_CACHE_DIR'] = str(cache)
        os.environ['TORCHINDUCTOR_COMPILE_THREADS'] = '2'
        import torch
        from safetensors.torch import load_file
        from peft import LoraConfig, get_peft_model, set_peft_model_state_dict
        from gptqmodel import GPTQModel, BACKEND
        from gptqmodel.nn_modules.qlinear import torch_awq
        data = json.loads((a.data / 'DONE.json').read_bytes())
        check_gate(a.gate, data, 8, True, 'AWQ_TORCH')
        if sha(a.data / 'train_tokens.jsonl') != data['train_tokens_sha256']:
            raise ValueError('RESUME_INPUT_TOKENS_DRIFT')
        benchmark = json.loads(a.benchmark.read_bytes())
        if not benchmark['complete'] or not all(x['bit_exact'] and x['output_and_input_gradient_exact'] for x in benchmark['results']):
            raise ValueError('DEQUANT_MICROBENCHMARK_NOT_PASSED')
        meta = json.loads((a.resume / 'CHECKPOINT.json').read_bytes())
        previous = (interrupted_resume_source(a.resume,a.recovery_record,meta) if a.recovery_record else
                    json.loads((a.resume.parent / 'TRAINED.json').read_bytes()))
        if sha(a.resume / 'adapter/adapter_model.safetensors') != meta['adapter_sha256'] or previous['adapter_sha256'] != meta['adapter_sha256']:
            raise ValueError('RESUME_ADAPTER_CHECKSUM_DRIFT')
        # This is our own checkpoint; retain all optimizer and RNG state.
        state = torch.load(a.resume / 'state.pt', map_location='cpu', weights_only=False)
        validate_resume(meta, data, state, sha(a.gate))
        if previous['rows_done'] != state['rows_done'] or previous['epoch_complete']:
            raise ValueError('RESUME_FINAL_POSITION_DRIFT')
        receipt = dict(source_checkpoint=str(a.resume), source_adapter_sha256=meta['adapter_sha256'],
            source_state_sha256=sha(a.resume / 'state.pt'), benchmark_sha256=sha(a.benchmark),
            resume_script_sha256=sha(Path(__file__)), baseline_trainer_sha256=sha(Path(__file__).with_name('v5_35b_train.py')),
            starting_step=state['steps'], starting_rows=state['rows_done'], total_optimizer_budget_seconds=a.total_budget_seconds,
            prior_training_seconds=previous['training_seconds'], fresh_initialization=False,
            optimizer_reset=False, data_reordered=False, quality_labels_used_for_speed_selection=False)
        if a.recovery_record:
            receipt['interrupted_recovery_record_sha256']=sha(a.recovery_record)
            receipt['interrupted_recovery_record']=json.loads(a.recovery_record.read_bytes())
        write(a.out / 'START.json', receipt)
        verify_model(a.model, a.manifest)
        records = read(a.data / 'train_tokens.jsonl')
        torch.set_num_threads(6); torch.manual_seed(20261019); random.seed(20261019)
        torch.backends.cuda.matmul.allow_tf32 = True
        with awq_loader_compat(a.model, a.out / 'LOADER_COMPATIBILITY.json'):
            quantized = GPTQModel.load(str(a.model), device='cuda:0', backend=BACKEND.AWQ_TORCH,
                dtype=torch.bfloat16, trust_remote_code=False, local_files_only=True, attn_implementation='sdpa')
        base = quantized.model
        for parameter in base.parameters(): parameter.requires_grad_(False)
        base.config.use_cache = False
        base.config.text_config.use_cache = False
        base.config.text_config.output_router_logits = False
        targets = target_names([n for n, m in base.named_modules() if isinstance(m, torch.nn.Linear)], 8, True)
        model = get_peft_model(base, LoraConfig(task_type='CAUSAL_LM', r=16, lora_alpha=32, lora_dropout=.05,
            target_modules=target_suffixes(True), layers_to_transform=list(range(32, 40)), layers_pattern='layers', bias='none'))
        injected = sorted(n.removeprefix('base_model.model.') for n,m in model.named_modules() if hasattr(m,'lora_A') and len(m.lora_A))
        if len(targets) != 50 or injected != targets or targets != meta['target_modules']:
            raise ValueError('RESUME_TARGET_MODULE_DRIFT')
        loaded = set_peft_model_state_dict(model, load_file(a.resume / 'adapter/adapter_model.safetensors'))
        if loaded.unexpected_keys or any('lora_' in n for n in loaded.missing_keys):
            raise ValueError('RESUME_ADAPTER_LOAD_INCOMPLETE')
        trainable = [(n,v) for n,v in model.named_parameters() if v.requires_grad]
        if len(trainable) != 100 or any('lora_' not in n or v.device.type != 'cuda' for n,v in trainable):
            raise ValueError('RESUME_TRAINABLE_BOUNDARY_DRIFT')
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant':False})
        underlying = model.get_base_model()
        if hasattr(underlying, '_require_grads_hook'): underlying.disable_input_require_grads()
        model.train()
        parameters = [v for n,v in trainable]
        optimizer = torch.optim.AdamW(parameters, lr=2e-5, weight_decay=.01, fused=True)
        optimizer.load_state_dict(state['optimizer'])
        if any(not bool(torch.isfinite(s[k]).all()) for s in optimizer.state.values() for k in ('exp_avg','exp_avg_sq')):
            raise ValueError('RESUME_NONFINITE_OPTIMIZER')
        yi=torch.tensor(data['answer_ids']['yes'],device='cuda'); ni=torch.tensor(data['answer_ids']['no'],device='cuda')
        def odds(record):
            ids=torch.tensor([record['ids']],device='cuda')
            with torch.autocast('cuda',dtype=torch.bfloat16):
                logits=model(input_ids=ids,attention_mask=torch.ones_like(ids),mm_token_type_ids=torch.zeros_like(ids),
                    use_cache=False,logits_to_keep=1).logits[0,-1].float()
            return torch.logsumexp(logits[yi],0)-torch.logsumexp(logits[ni],0)
        def restore_rng():
            torch.set_rng_state(state['cpu_rng']); torch.cuda.set_rng_state_all(state['cuda_rng'])
        original = torch_awq.dequantize_gemm
        compiled = torch.compile(original, fullgraph=True, dynamic=False)
        # Warm compilation outside both timed model arms and dropout RNG streams.
        timer=time.monotonic(); shapes=set();warm=[]
        for name,module in base.named_modules():
            if not isinstance(module,torch_awq.AwqTorchLinear):continue
            key=(tuple(module.qweight.shape),tuple(module.scales.shape))
            if key in shapes:continue
            shapes.add(key)
            kwargs=dict(qweight=module.qweight,qzeros=module.qzeros,scales=module.scales,bits=4,group_size=32)
            with torch.autocast('cuda',dtype=torch.bfloat16):
                ref=original(**kwargs);fast=compiled(**kwargs)
            exact=torch.equal(ref,fast)
            warm.append(dict(name=name,shape=list(ref.shape),bit_exact=exact))
            if not exact:raise ValueError('WARMED_DEQUANT_WEIGHT_NOT_EXACT')
        torch.cuda.synchronize();warm_seconds=time.monotonic()-timer
        write(a.out/'DEQUANT_WARMUP.json',dict(complete=True,examples=warm,seconds=warm_seconds))
        probes=[]
        # Same inputs, saved dropout RNG, adapter and gradients for both arms.
        probe_indices=[] if a.recovery_record else state['order'][state['rows_done']:state['rows_done']+2]
        for index in probe_indices:
            arms=[]
            for key,fn in [('baseline',original),('baseline_repeat',original),('compiled',compiled)]:
                torch_awq.dequantize_gemm=fn; restore_rng(); optimizer.zero_grad(set_to_none=True)
                torch.cuda.synchronize(); timer=time.monotonic()
                score=odds(records[index]); loss=torch.nn.functional.binary_cross_entropy_with_logits(score,score.new_tensor(float(records[index]['label'])))
                loss.backward(); torch.cuda.synchronize()
                if any(v.grad is None or not bool(torch.isfinite(v.grad).all()) for v in parameters):
                    raise ValueError('PROBE_MISSING_OR_NONFINITE_GRADIENT')
                grads=[v.grad.detach().clone() for v in parameters]
                rng_hash=hashlib.sha256(torch.cuda.get_rng_state().cpu().numpy().tobytes()).hexdigest()
                arms.append((float(score.detach()),float(loss.detach()),grads,time.monotonic()-timer,rng_hash))
            def compare(left,right):
                diffs=[float((x-y).abs().max()) for x,y in zip(left[2],right[2])]
                scale=max(float(x.abs().max()) for x in left[2])
                diff2=[float((x.float()-y.float()).square().sum()) for x,y in zip(left[2],right[2])]
                ref2=[float(x.float().square().sum()) for x in left[2]]
                return dict(score_abs_delta=abs(left[0]-right[0]),loss_abs_delta=abs(left[1]-right[1]),
                    max_gradient_abs_delta=max(diffs),gradient_reference_max_abs=scale,
                    gradient_relative_l2=math.sqrt(sum(diff2)/max(sum(ref2),1e-30)),
                    worst_tensor_gradient_relative_l2=max(math.sqrt(d/max(n,1e-30)) for d,n in zip(diff2,ref2)),
                    max_gradient_delta_relative_to_largest=max(diffs)/max(scale,1e-30),
                    bit_exact=left[0]==right[0] and left[1]==right[1] and all(torch.equal(x,y) for x,y in zip(left[2],right[2])),
                    post_dropout_rng_equal=left[4]==right[4])
            control=compare(arms[0],arms[1]);treatment=compare(arms[0],arms[2])
            exact=control['bit_exact'] and treatment['bit_exact']
            item=dict(id=records[index]['id'],tokens=records[index]['tokens'],score_and_gradients_exact=exact,
                baseline_seconds=arms[0][3],compiled_seconds=arms[2][3],score=arms[0][0],
                baseline_repeat_control=control,compiled_comparison=treatment)
            probes.append(item); print(json.dumps(dict(event='resume_speed_probe',**item)),flush=True)
            if not math.isfinite(arms[0][0]): raise ValueError('NONFINITE_REFERENCE_SPEED_PROBE')
        accepted=(all(admit_speed_probe(x) for x in probes) and
                  warm_seconds+sum(x['compiled_seconds'] for x in probes)<.9*sum(x['baseline_seconds'] for x in probes))
        if a.recovery_record:accepted=True  # source admission authenticated above; this is the same admitted recipe
        write(a.out/'SPEED_GATE.json',dict(complete=True,probes=probes,optimizer_updates=0,quality_selection=False,
            compiled_accepted=accepted,full_model_bit_exact=None if a.recovery_record else all(x['score_and_gradients_exact'] for x in probes),
            source_admission_sha256=meta.get('speed_gate_sha256') if a.recovery_record else None,
            reused_checkpoint_admission=bool(a.recovery_record),warmed_weight_parity=True,
            criterion='warmed weights exact; dropout RNG equal; score/loss deltas <=1e-5; gradient relative L2 <=0.005 and <=2x reference-repeat noise +1e-7; worst tensor relative L2 <=0.02; gradient max delta <=2x control +1e-7; >=10 percent faster including warmup',
            status='EXPLORATORY_NUMERIC_NOISE_BOUNDED_NOT_ABSOLUTE_EQUIVALENCE'))
        torch_awq.dequantize_gemm=compiled if accepted else original
        restore_rng(); optimizer.zero_grad(set_to_none=True)
        stopped=False
        def stop(_sig,_frame):
            nonlocal stopped
            stopped=True
        signal.signal(signal.SIGTERM,stop)
        steps=state['steps']; rows_done=state['rows_done']; forwarded=0
        train_started=time.monotonic(); prior_seconds=previous['training_seconds']
        remaining=max(0,a.total_budget_seconds-prior_seconds)
        meta=dict(meta,resume=receipt,speed_gate_sha256=sha(a.out/'SPEED_GATE.json'),compiled_awq_dequant=accepted,
                  optimizer_budget_seconds=a.total_budget_seconds)
        write(a.out/'MODEL_READY.json',meta)
        def checkpoint(name):
            folder=a.out/name; folder.mkdir(exist_ok=False)
            model.save_pretrained(folder/'adapter',safe_serialization=True)
            torch.save(dict(optimizer=optimizer.state_dict(),cpu_rng=torch.get_rng_state(),cuda_rng=torch.cuda.get_rng_state_all(),
                order=state['order'],rows_done=rows_done,steps=steps),folder/'state.pt')
            write(folder/'CHECKPOINT.json',dict(meta,rows_done=rows_done,steps=steps,optimizer_updates=steps,
                adapter_sha256=sha(folder/'adapter/adapter_model.safetensors')))
        torch.cuda.reset_peak_memory_stats()
        with (a.out/'training.jsonl').open('w',buffering=1) as log:
            for offset in range(rows_done,len(records),16):
                if stopped or time.monotonic()-train_started>=remaining:break
                batch=state['order'][offset:offset+16]; optimizer.zero_grad(set_to_none=True); losses=[]
                for index in batch:
                    if stopped or time.monotonic()-train_started>=remaining:break
                    score=odds(records[index]); loss=torch.nn.functional.binary_cross_entropy_with_logits(score,score.new_tensor(float(records[index]['label'])))
                    if not bool(torch.isfinite(loss)):raise ValueError('NONFINITE_TRAIN_LOSS')
                    (loss/len(batch)).backward(); losses.append(float(loss.detach()));forwarded+=1
                if len(losses)!=len(batch):optimizer.zero_grad(set_to_none=True);break
                norm=float(torch.nn.utils.clip_grad_norm_(parameters,1.0))
                if not math.isfinite(norm):raise ValueError('NONFINITE_TRAIN_GRADIENT')
                for group in optimizer.param_groups:group['lr']=2e-5*min(1.0,(steps+1)/5)
                optimizer.step();steps+=1;rows_done+=len(batch)
                item=dict(step=steps,rows_done=rows_done,rows_total=len(records),loss=sum(losses)/len(losses),grad_norm=norm,
                    seconds=prior_seconds+time.monotonic()-train_started,resumed_seconds=time.monotonic()-train_started)
                log.write(json.dumps(item)+'\n');write(a.out/'PROGRESS.json',item);print(json.dumps(dict(event='train',**item)),flush=True)
                if a.recovery_record or steps==state['steps']+1 or steps%10==0:checkpoint('checkpoint-%04d'%steps)
        checkpoint('final');model.save_pretrained(a.out/'adapter',safe_serialization=True)
        write(a.out/'TRAINED.json',dict(meta,complete=True,optimizer_updates=steps,rows_done=rows_done,
            rows_forwarded_since_resume=forwarded,epoch_fraction=rows_done/len(records),epoch_complete=rows_done==len(records),
            training_seconds=prior_seconds+time.monotonic()-train_started,adapter_sha256=sha(a.out/'adapter/adapter_model.safetensors'),
            peak_allocated=torch.cuda.max_memory_allocated(),peak_reserved=torch.cuda.max_memory_reserved()))
    except Exception as e:
        write(a.out/'FAIL.json',dict(complete=False,error_type=type(e).__name__,error=str(e),traceback=traceback.format_exc(),seconds=time.monotonic()-started))
        raise


if __name__=='__main__':main()
