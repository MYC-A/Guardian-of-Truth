"""Bounded microbenchmark; never loads or changes the active training model."""
import argparse
import json
import os
from pathlib import Path
import time


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--model', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    a.out.mkdir(exist_ok=False)
    os.environ['TORCHINDUCTOR_CACHE_DIR'] = str(a.out / 'compile-cache')
    os.environ['TORCHINDUCTOR_COMPILE_THREADS'] = '2'
    import torch
    from safetensors import safe_open
    from gptqmodel.quantization.awq.utils.packing_utils import dequantize_gemm
    torch.set_num_threads(2)
    torch.manual_seed(73019)
    index = json.loads((a.model / 'model.safetensors.index.json').read_bytes())['weight_map']
    names = sorted(k[:-8] for k in index if k.endswith('.qweight') and '.experts.' in k)
    selected = [names[i] for i in (0, 1, 2, len(names)//2, len(names)-2, len(names)-1)]
    compiled = torch.compile(dequantize_gemm, fullgraph=True, dynamic=False)
    results = []
    for name in selected:
        weights = {}
        for suffix in ('qweight', 'qzeros', 'scales'):
            key = name + '.' + suffix
            with safe_open(a.model / index[key], framework='pt', device='cpu') as f:
                weights[suffix] = f.get_tensor(key).to('cuda')
        weights['scales'] = weights['scales'].to(torch.bfloat16)
        args = dict(**weights, bits=4, group_size=32)
        reference = dequantize_gemm(**args)
        actual = compiled(**args)
        torch.cuda.synchronize()
        if not torch.equal(reference, actual):
            raise ValueError('COMPILED_DEQUANT_NOT_BIT_EXACT:' + name)
        if not bool(torch.isfinite(actual).all()):
            raise ValueError('NONFINITE_WEIGHTS:' + name)
        x = torch.randn((32, reference.shape[0]), device='cuda', dtype=torch.bfloat16, requires_grad=True)
        y = x @ reference
        z = x @ actual
        dy = torch.autograd.grad(y.float().square().mean(), x)[0]
        dz = torch.autograd.grad(z.float().square().mean(), x)[0]
        if not torch.equal(y, z) or not torch.equal(dy, dz):
            raise ValueError('OUTPUT_OR_INPUT_GRADIENT_CHANGED:' + name)
        times = {'reference': [], 'compiled': []}
        for _ in range(3):
            for key, fn in [('reference', dequantize_gemm), ('compiled', compiled)]:
                torch.cuda.synchronize()
                start = time.monotonic()
                for _ in range(40):
                    value = fn(**args)
                torch.cuda.synchronize()
                times[key].append((time.monotonic() - start) / 40)
        item = dict(name=name, shape=list(reference.shape), bit_exact=True,
                    output_and_input_gradient_exact=True, seconds_per_call=times,
                    speedup=sum(times['reference']) / sum(times['compiled']))
        results.append(item)
        print(json.dumps(item), flush=True)
    receipt = dict(complete=True, results=results, active_training_modified=False,
                   note='Shared GPU microbenchmark; not an end-to-end training speed claim')
    (a.out / 'DONE.json').write_text(json.dumps(receipt, indent=2) + '\n')


if __name__ == '__main__':
    main()
