"""Native deployment proof for a zero and deliberately nonzero TRAIN-only adapter."""
import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src'), str(ROOT / 'scripts')]
from v5_35b_common import BASE_REVISION, read, sha, verify_model, write


def worker(args):
    import torch
    from safetensors.torch import load_file, save_file
    from vllm import LLM, SamplingParams
    from vllm.lora.request import LoRARequest
    from scripts.judge_stage import answer_ids, answer_score, engine_kwargs
    pilot = json.loads((args.pilot / 'DONE.json').read_bytes())
    data = json.loads((args.data / 'DONE.json').read_bytes())
    if not pilot['complete'] or pilot['optimizer_updates'] != 0 or not pilot['technical_feasible']:
        raise ValueError('PILOT_NOT_FEASIBLE')
    zero = args.pilot / 'zero-adapter'
    if sha(zero / 'adapter_model.safetensors') != pilot['zero_adapter_sha256']:
        raise ValueError('ZERO_ADAPTER_DRIFT')
    if sha(args.data / 'pilot_tokens.jsonl') != data['pilot_tokens_sha256']:
        raise ValueError('PILOT_INPUT_DRIFT')
    verify_model(args.model, args.manifest)
    tensors = load_file(zero / 'adapter_model.safetensors', device='cpu')
    bkeys = [key for key in tensors if '.lora_B.' in key]
    if not bkeys or any(bool(torch.count_nonzero(tensors[key])) for key in bkeys):
        raise ValueError('NONZERO_PILOT_ADAPTER')
    generator = torch.Generator(device='cpu').manual_seed(20261019)
    for key in sorted(bkeys):
        tensors[key] = torch.randn(tensors[key].shape, generator=generator, dtype=tensors[key].dtype) * .01
    nonzero = args.out / 'technical-nonzero-adapter'; nonzero.mkdir(exist_ok=False)
    (nonzero / 'adapter_config.json').write_bytes((zero / 'adapter_config.json').read_bytes())
    save_file(tensors, nonzero / 'adapter_model.safetensors', metadata={'format': 'pt'})
    del tensors
    cfg = json.loads((ROOT / 'submission/JUDGE_BLEND40.json').read_bytes())
    cfg.update(max_model_len=max(16384, data['max_tokens'] + 16), gpu_memory_utilization=.85,
               max_num_seqs=1, max_num_batched_tokens=16384, dtype='bfloat16', multimodal=False,
               engine_overrides={'enforce_eager': True})
    kwargs, dropped = engine_kwargs(str(args.model), cfg)
    kwargs.update(enable_lora=True, max_lora_rank=16, max_loras=1, max_cpu_loras=2)
    llm = LLM(**kwargs)
    yes, no = answer_ids(llm.get_tokenizer())
    if sorted(yes) != data['answer_ids']['yes'] or sorted(no) != data['answer_ids']['no']:
        raise ValueError('PRODUCTION_ANSWER_TOKEN_DRIFT')
    params = SamplingParams(temperature=1.0, top_p=1.0, max_tokens=1, logprobs=20, seed=0,
                            allowed_token_ids=sorted(yes | no))
    rows = read(args.data / 'pilot_tokens.jsonl')
    if len(rows) != 3 or any('label' in row for row in rows):
        raise ValueError('PILOT_NATIVE_INPUT_SCOPE')
    scores = {}
    for name, request in [('base', None), ('zero', LoRARequest('v5-zero', 1, str(zero.resolve()))),
                          ('nonzero', LoRARequest('v5-nonzero', 2, str(nonzero.resolve())))]:
        outputs = llm.generate([dict(prompt_token_ids=row['ids']) for row in rows], params,
                               use_tqdm=False, lora_request=request)
        if len(outputs) != len(rows):
            raise ValueError('NATIVE_OUTPUT_COUNT')
        scores[name] = []
        for row, output in zip(rows, outputs):
            if list(output.prompt_token_ids) != row['ids']:
                raise ValueError('NATIVE_TOKEN_ID_DRIFT')
            score, exact = answer_score(output, yes, no)
            if not exact or score is None or not math.isfinite(score):
                raise ValueError('NATIVE_INEXACT_SCORE')
            scores[name].append(score)
    zero_delta = max(abs(x - y) for x, y in zip(scores['base'], scores['zero']))
    changed = max(abs(x - y) for x, y in zip(scores['zero'], scores['nonzero']))
    if zero_delta > .001:
        raise ValueError('NATIVE_ZERO_ADAPTER_PARITY:' + str(zero_delta))
    if changed <= .0001:
        raise ValueError('NATIVE_ADAPTER_EFFECT_NOT_OBSERVED')
    write(args.out / 'WORKER_DONE.json', dict(complete=True, base_revision=BASE_REVISION, rows=3,
        exact_calls=9, scores=scores, zero_adapter_max_abs_delta=zero_delta, nonzero_max_abs_delta=changed,
        nonzero_adapter_binding_proven=True, zero_adapter_sha256=pilot['zero_adapter_sha256'],
        nonzero_adapter_sha256=sha(nonzero / 'adapter_model.safetensors'),
        pilot_tokens_sha256=data['pilot_tokens_sha256'], layers=pilot['layers'], shared=pilot['shared'],
        dropped_engine_kwargs=dropped, scope='TRAIN technical binding only; no quality measurement'))


def main():
    parser = argparse.ArgumentParser()
    for name in ('model', 'manifest', 'pilot', 'data', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--worker', action='store_true')
    args = parser.parse_args()
    if args.worker:
        try:
            worker(args)
            sys.stdout.flush(); sys.stderr.flush(); os._exit(0)
        except Exception as error:
            write(args.out / 'WORKER_FAIL.json', dict(error_type=type(error).__name__, error=str(error),
                                                     traceback=traceback.format_exc()))
            traceback.print_exc(); sys.stdout.flush(); sys.stderr.flush(); os._exit(1)
    from scripts.judge_submission import kill_group
    args.out.mkdir(exist_ok=False)
    started = time.monotonic(); process = None
    try:
        write(args.out / 'START.json', dict(scope='TRAIN-only native zero/nonzero LoRA binding', optimizer_updates=0))
        with (args.out / 'worker.log').open('w', encoding='utf-8') as log:
            process = subprocess.Popen([sys.executable, str(Path(__file__)), *sys.argv[1:], '--worker'],
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                code = process.wait(timeout=600)
            finally:
                gone = kill_group(process, grace=3)
        if code != 0 or not gone:
            raise ValueError('NATIVE_WORKER_FAILED:' + str(code))
        result = json.loads((args.out / 'WORKER_DONE.json').read_bytes())
        result.update(seconds=time.monotonic() - started, group_gone=gone)
        write(args.out / 'DONE.json', result)
        print(json.dumps(result), flush=True)
    except Exception as error:
        write(args.out / 'FAIL.json', dict(complete=False, error_type=type(error).__name__, error=str(error),
                                         seconds=time.monotonic() - started))
        raise


if __name__ == '__main__':
    main()
