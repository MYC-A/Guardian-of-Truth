"""Finite AWQ/BF16 35B LoRA pilot or gated training; V4 runtime is not modified."""
import argparse
import importlib.metadata
import json
import math
from pathlib import Path
import random
import signal
import sys
import time
import traceback
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src'), str(ROOT / 'scripts')]
from v5_35b_common import BASE_ID, BASE_REVISION, FROZEN_SHA256, TRAIN_SHA256, awq_loader_compat, read, sha, target_names, target_suffixes, verify_model, write


def check_gate(path, data, layers, shared, backend='AWQ_TORCH'):
    if path is None:
        raise ValueError('NATIVE_PREFLIGHT_GATE_REQUIRED')
    gate = json.loads(Path(path).read_bytes())
    if (gate.get('layers'), gate.get('shared')) != (layers, shared):
        raise ValueError('TRAINING_PROFILE_DRIFT')
    if gate.get('train_tokens_sha256') != data['train_tokens_sha256']:
        raise ValueError('GATE_DATA_DRIFT')
    receipts = {}
    for name in ('pilot', 'native'):
        file = Path(gate[name]['path'])
        if sha(file) != gate[name]['sha256']:
            raise ValueError('GATE_RECEIPT_DRIFT:' + name)
        receipt = json.loads(file.read_bytes())
        receipts[name] = receipt
        if not receipt.get('complete'):
            raise ValueError('INCOMPLETE_GATE:' + name)
        if name == 'pilot' and (receipt.get('optimizer_updates') != 0 or not receipt.get('technical_feasible')):
            raise ValueError('PILOT_NOT_FEASIBLE')
        if name == 'native' and not receipt.get('nonzero_adapter_binding_proven'):
            raise ValueError('NATIVE_ADAPTER_BINDING_NOT_PROVEN')
    pilot, native = receipts['pilot'], receipts['native']
    if (pilot.get('layers'), pilot.get('shared'), pilot.get('train_tokens_sha256')) != (layers, shared, data['train_tokens_sha256']):
        raise ValueError('PILOT_PROFILE_DRIFT')
    if pilot.get('source_sha256', {}).get('v5_35b_train.py') != sha(Path(__file__)):
        raise ValueError('TRAINER_CHANGED_AFTER_PILOT')
    if pilot.get('source_sha256', {}).get('v5_35b_common.py') != sha(Path(__file__).with_name('v5_35b_common.py')):
        raise ValueError('TRAINING_HELPER_CHANGED_AFTER_PILOT')
    if native.get('source_sha256') != sha(Path(__file__).with_name('v5_35b_native_probe.py')):
        raise ValueError('NATIVE_PROBE_CHANGED_AFTER_GATE')
    if native.get('zero_adapter_sha256') != pilot.get('zero_adapter_sha256') or native.get('base_revision') != BASE_REVISION:
        raise ValueError('NATIVE_MODEL_OR_ADAPTER_DRIFT')
    if native.get('pilot_tokens_sha256') != data['pilot_tokens_sha256']:
        raise ValueError('NATIVE_INPUT_DRIFT')
    if gate.get('backend', 'AWQ_TORCH') != backend or pilot.get('backend') != backend:
        raise ValueError('TRAINING_BACKEND_DRIFT')
    return gate


def main():
    parser = argparse.ArgumentParser()
    for name in ('model', 'manifest', 'data', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--pilot', action='store_true')
    parser.add_argument('--layers', type=int, choices=(8, 40), default=40)
    parser.add_argument('--attention-only', action='store_true')
    parser.add_argument('--backend', choices=('AWQ_TORCH', 'AWQ_GEMM_TRITON'), default='AWQ_TORCH')
    parser.add_argument('--gate', type=Path)
    parser.add_argument('--budget-seconds', type=int, default=14400)
    args = parser.parse_args()
    args.out.mkdir(exist_ok=False)
    started = time.monotonic()
    try:
        if not 60 <= args.budget_seconds <= 32400:
            raise ValueError('UNREGISTERED_TRAINING_BUDGET')
        data = json.loads((args.data / 'DONE.json').read_bytes())
        if not data['complete'] or data['base_revision'] != BASE_REVISION or data['frozen_sha256'] != FROZEN_SHA256 or data['train_source_sha256'] != TRAIN_SHA256:
            raise ValueError('PREPARED_DATA_IDENTITY_DRIFT')
        if sha(args.data / 'train_tokens.jsonl') != data['train_tokens_sha256']:
            raise ValueError('ENCODED_TRAIN_DRIFT')
        records = read(args.data / 'train_tokens.jsonl')
        if len(records) != 1458 or any(r['label'] not in (0, 1) for r in records):
            raise ValueError('TRAIN_ROWS_OR_LABELS_DRIFT')
        shared = not args.attention_only
        gate = None if args.pilot else check_gate(args.gate, data, args.layers, shared, args.backend)
        meta = dict(base_id=BASE_ID, base_revision=BASE_REVISION, pilot=args.pilot, optimizer_updates=0,
                    layers=args.layers, shared=shared, rank=16, alpha=32, dropout=.05, learning_rate=2e-5,
                    effective_batch=16, seed=20261019, rows=len(records), tokens=data['tokens'],
                    optimizer_budget_seconds=args.budget_seconds,
                    train_tokens_sha256=data['train_tokens_sha256'], frozen_sha256=FROZEN_SHA256,
                    gate_sha256=sha(args.gate) if gate else None,
                    source_sha256={name: sha(Path(__file__).with_name(name)) for name in
                                   ('v5_35b_train.py', 'v5_35b_common.py')},
                    objective='BCE exact YES-vs-NO next-token log-odds', context_trimmed=False,
                    human_reviewed=False, status='EXPLORATORY_ONLY_HUMAN_UNVERIFIED')
        write(args.out / 'START.json', meta)
        verify_model(args.model, args.manifest)
        write(args.out / 'MODEL_VERIFIED.json', dict(complete=True, manifest_sha256=sha(args.manifest)))
        import torch
        from peft import LoraConfig, get_peft_model
        from gptqmodel import GPTQModel, BACKEND
        dtype = torch.bfloat16 if args.backend == 'AWQ_TORCH' else torch.float16
        loss_scale = 1.0 if dtype == torch.bfloat16 else 128.0
        torch.set_num_threads(6)
        torch.manual_seed(20261019)
        random.seed(20261019)
        torch.backends.cuda.matmul.allow_tf32 = True
        meta['versions'] = {n: importlib.metadata.version(n) for n in
                            ('torch', 'transformers', 'peft', 'gptqmodel', 'optimum')}
        for name in ('flash-linear-attention', 'fla-core', 'causal-conv1d'):
            try:
                meta['versions'][name] = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                meta['versions'][name] = None
        timer = time.monotonic()
        print(json.dumps(dict(event='load_35b_awq', backend=args.backend, dtype=str(dtype))), flush=True)
        with awq_loader_compat(args.model, args.out / 'LOADER_COMPATIBILITY.json'):
            quantized = GPTQModel.load(str(args.model), device='cuda:0', backend=getattr(BACKEND, args.backend),
                                       dtype=dtype, trust_remote_code=False, local_files_only=True,
                                       attn_implementation='sdpa')
        base = quantized.model
        for parameter in base.parameters():
            parameter.requires_grad_(False)
        base.config.use_cache = False
        if hasattr(base.config, 'text_config'):
            base.config.text_config.use_cache = False
            base.config.text_config.output_router_logits = False
        targets = target_names([n for n, m in base.named_modules() if isinstance(m, torch.nn.Linear)], args.layers, shared)
        samples = [dict(name=n, type=type(m).__name__) for n, m in base.named_modules()
                   if '.language_model.' in n and any(n.endswith('.' + s) for s in target_suffixes(shared))]
        write(args.out / 'MODEL_MODULES.json', dict(model_type=type(base).__name__, target_count=len(targets),
                                                  projection_modules=samples))
        expected = (250 if shared else 130) if args.layers == 40 else (50 if shared else 26)
        if len(targets) != expected:
            raise ValueError('TARGET_MODULE_SET_DRIFT:' + str(len(targets)))
        model = get_peft_model(base, LoraConfig(task_type='CAUSAL_LM', r=16, lora_alpha=32, lora_dropout=.05,
            target_modules=target_suffixes(shared), layers_to_transform=list(range(40 - args.layers, 40)),
            layers_pattern='layers', bias='none'))
        injected = sorted(n.removeprefix('base_model.model.') for n, m in model.named_modules()
                          if hasattr(m, 'lora_A') and len(m.lora_A))
        if injected != targets:
            raise ValueError('INJECTED_TARGET_SET_DRIFT')
        trainable = [(n, p) for n, p in model.named_parameters() if p.requires_grad]
        if not trainable or any('.lora_A.' not in n and '.lora_B.' not in n for n, _ in trainable):
            raise ValueError('NON_LORA_TRAINABLE_PARAMETER')
        if any(p.device.type != 'cuda' for _, p in trainable):
            raise ValueError('TRAINABLE_PARAMETER_NOT_ON_GPU')
        meta.update(target_modules=targets, trainable_parameters=sum(p.numel() for _, p in trainable),
                    model_load_seconds=time.monotonic() - timer, dtype=str(dtype).removeprefix('torch.'),
                    backend=args.backend, loss_scale=loss_scale)
        meta['gdn_kernels'] = sorted({str(getattr(m.chunk_gated_delta_rule, '__module__', 'unknown')) + '.' +
                                      str(getattr(m.chunk_gated_delta_rule, '__name__', 'unknown'))
                                      for m in base.modules() if hasattr(m, 'chunk_gated_delta_rule')})
        write(args.out / 'MODEL_READY.json', meta)
        yi = torch.tensor(data['answer_ids']['yes'], device='cuda')
        ni = torch.tensor(data['answer_ids']['no'], device='cuda')

        def odds(record):
            ids = torch.tensor([record['ids']], device='cuda')
            with torch.autocast('cuda', dtype=dtype):
                logits = model(input_ids=ids, attention_mask=torch.ones_like(ids),
                    mm_token_type_ids=torch.zeros_like(ids), use_cache=False, logits_to_keep=1).logits[0, -1].float()
            return torch.logsumexp(logits[yi], 0) - torch.logsumexp(logits[ni], 0)

        if any(bool(torch.count_nonzero(p)) for n, p in trainable if '.lora_B.' in n):
            raise ValueError('ADAPTER_NOT_FRESH_ZERO_B')
        pilots = sorted(records, key=lambda r: (-r['tokens'], r['id']))[:3]
        if args.pilot:
            model.eval()
            with torch.no_grad():
                zero = float(odds(pilots[0]))
                with model.disable_adapter():
                    disabled = float(odds(pilots[0]))
            if not math.isfinite(zero) or abs(zero - disabled) > 1e-5:
                raise ValueError('ZERO_ADAPTER_HF_PARITY_FAILED')
            model.save_pretrained(args.out / 'zero-adapter', safe_serialization=True)
            meta.update(zero_adapter_sha256=sha(args.out / 'zero-adapter/adapter_model.safetensors'),
                        zero_adapter_score=zero, disabled_adapter_score=disabled)
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant': False})
        underlying = model.get_base_model()
        if hasattr(underlying, '_require_grads_hook'):
            underlying.disable_input_require_grads()
        model.train()
        torch.cuda.reset_peak_memory_stats()
        if args.pilot:
            measurements = []
            for record in pilots:
                write(args.out / 'PILOT_STEP_START.json', dict(id=record['id'], tokens=record['tokens'],
                    phase='forward_backward', rows_done=len(measurements), optimizer_updates=0))
                model.zero_grad(set_to_none=True)
                torch.cuda.synchronize(); timer = time.monotonic()
                score = odds(record)
                loss = torch.nn.functional.binary_cross_entropy_with_logits(score, score.new_tensor(float(record['label'])))
                if not bool(torch.isfinite(loss)):
                    raise ValueError('NONFINITE_PILOT_LOSS')
                (loss * loss_scale).backward()
                for _, parameter in trainable:
                    if parameter.grad is not None:
                        parameter.grad.div_(loss_scale)
                grads = [(n, p.grad) for n, p in trainable]
                if any(g is None for _, g in grads):
                    raise ValueError('MISSING_LORA_GRADIENT')
                if not all(bool(torch.isfinite(g).all()) for _, g in grads):
                    raise ValueError('NONFINITE_PILOT_GRADIENT')
                bnorm = math.sqrt(sum(float(g.float().square().sum()) for n, g in grads if '.lora_B.' in n))
                if not math.isfinite(bnorm) or bnorm <= 0:
                    raise ValueError('ZERO_LORA_B_GRADIENT')
                if any(p.grad is not None for p in base.parameters() if not p.requires_grad):
                    raise ValueError('FROZEN_BASE_HAS_GRADIENT')
                torch.cuda.synchronize()
                item = dict(id=record['id'], tokens=record['tokens'], seconds=time.monotonic() - timer,
                    loss=float(loss.detach()), grad_B_norm=bnorm, peak_allocated=torch.cuda.max_memory_allocated(),
                    peak_reserved=torch.cuda.max_memory_reserved())
                measurements.append(item)
                print(json.dumps(dict(event='pilot_backward', **item)), flush=True)
                write(args.out / 'PROGRESS.json', dict(phase='PILOT', rows=len(measurements), optimizer_updates=0, last=item))
            tps = sum(r['tokens'] for r in measurements) / sum(r['seconds'] for r in measurements)
            estimate = data['tokens'] / tps * 1.15
            optimizer_bytes = 8 * meta['trainable_parameters']
            peak = max(r['peak_allocated'] for r in measurements)
            meta.update(complete=True, optimizer_updates=0, measurements=measurements, tokens_per_second=tps,
                        estimated_epoch_seconds=estimate, estimated_optimizer_bytes=optimizer_bytes,
                        technical_feasible=peak + optimizer_bytes + (1 << 30) < 45 * (1 << 30),
                        epoch_fits_budget=estimate <= args.budget_seconds,
                        seconds=time.monotonic() - started)
            write(args.out / 'DONE.json', meta)
            return

        stopped = False
        def stop(_signal, _frame):
            nonlocal stopped
            stopped = True
        signal.signal(signal.SIGTERM, stop)
        parameters = [p for _, p in trainable]
        optimizer = torch.optim.AdamW(parameters, lr=2e-5, weight_decay=.01, fused=True)
        order = list(range(len(records))); random.Random(20261019).shuffle(order)
        steps = 0; rows_done = 0; forwarded = 0; train_started = time.monotonic()
        def checkpoint(name):
            folder = args.out / name; folder.mkdir(exist_ok=False)
            model.save_pretrained(folder / 'adapter', safe_serialization=True)
            torch.save(dict(optimizer=optimizer.state_dict(), cpu_rng=torch.get_rng_state(),
                            cuda_rng=torch.cuda.get_rng_state_all(), order=order, rows_done=rows_done,
                            steps=steps), folder / 'state.pt')
            write(folder / 'CHECKPOINT.json', dict(meta, rows_done=rows_done, steps=steps, optimizer_updates=steps,
                adapter_sha256=sha(folder / 'adapter/adapter_model.safetensors')))
        with (args.out / 'training.jsonl').open('w', encoding='utf-8', buffering=1) as log:
            for offset in range(0, len(order), 16):
                if stopped or time.monotonic() - train_started >= args.budget_seconds:
                    break
                batch = order[offset:offset + 16]; optimizer.zero_grad(set_to_none=True); losses = []
                for index in batch:
                    if stopped or time.monotonic() - train_started >= args.budget_seconds:
                        break
                    record = records[index]; score = odds(record)
                    loss = torch.nn.functional.binary_cross_entropy_with_logits(score, score.new_tensor(float(record['label'])))
                    if not bool(torch.isfinite(loss)):
                        raise ValueError('NONFINITE_TRAIN_LOSS')
                    (loss * (loss_scale / len(batch))).backward(); losses.append(float(loss.detach())); forwarded += 1
                if len(losses) != len(batch):
                    optimizer.zero_grad(set_to_none=True); break
                for parameter in parameters:
                    if parameter.grad is not None:
                        parameter.grad.div_(loss_scale)
                norm = float(torch.nn.utils.clip_grad_norm_(parameters, 1.0))
                if not math.isfinite(norm):
                    raise ValueError('NONFINITE_TRAIN_GRADIENT_NORM')
                for group in optimizer.param_groups:
                    group['lr'] = 2e-5 * min(1.0, (steps + 1) / 5)
                optimizer.step(); steps += 1; rows_done += len(batch)
                item = dict(step=steps, rows_done=rows_done, rows_total=len(records), loss=sum(losses) / len(losses),
                            grad_norm=norm, seconds=time.monotonic() - train_started)
                log.write(json.dumps(item) + '\n'); write(args.out / 'PROGRESS.json', item)
                print(json.dumps(dict(event='train', **item)), flush=True)
                if steps % 10 == 0:
                    checkpoint('checkpoint-%04d' % steps)
        if not steps:
            raise ValueError('ZERO_OPTIMIZER_UPDATES')
        checkpoint('final')
        model.save_pretrained(args.out / 'adapter', safe_serialization=True)
        meta.update(complete=True, optimizer_updates=steps, rows_done=rows_done, rows_forwarded=forwarded,
                    epoch_fraction=rows_done / len(records), epoch_complete=rows_done == len(records),
                    training_seconds=time.monotonic() - train_started,
                    adapter_sha256=sha(args.out / 'adapter/adapter_model.safetensors'),
                    peak_allocated=torch.cuda.max_memory_allocated(), peak_reserved=torch.cuda.max_memory_reserved())
        write(args.out / 'TRAINED.json', meta)
        print(json.dumps(dict(event='trained', rows=rows_done, steps=steps, epoch_complete=meta['epoch_complete'])), flush=True)
    except Exception as error:
        write(args.out / 'FAIL.json', dict(complete=False, error_type=type(error).__name__, error=str(error),
                                         seconds=time.monotonic() - started, traceback=traceback.format_exc()))
        raise


if __name__ == '__main__':
    main()
