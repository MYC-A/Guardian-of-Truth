#!/usr/bin/env python3
"""Offline FP8 (e4m3) block-128 weight quantization of Linear weights in a BF16
safetensors checkpoint, in the same format as Qwen/*-FP8 checkpoints
(quant_method fp8, weight_block_size [128,128], tensor `<name>.weight_scale_inv`
= dequant multiplier per block). Only `model.layers.*` projection weights are
quantized; embeddings, norms and lm_head stay BF16."""
import json, re, shutil, sys
from pathlib import Path
import torch
from safetensors.torch import load_file, save_file
src, dst = Path(sys.argv[1]), Path(sys.argv[2]); dst.mkdir(parents=True, exist_ok=True)
B, FMAX = 128, torch.finfo(torch.float8_e4m3fn).max
PAT = re.compile(r"^model\.layers\.\d+\.(self_attn\.(q|k|v|o)_proj|mlp\.(gate|up|down)_proj)\.weight$")
dev = "cuda" if torch.cuda.is_available() else "cpu"
idx = json.loads((src / "model.safetensors.index.json").read_text()); wm = {}; nq = 0; maxrel = 0.0
for shard in sorted(set(idx["weight_map"].values())):
    t = load_file(str(src / shard)); out = {}
    for k, w in t.items():
        if not PAT.match(k):
            out[k] = w; wm[k] = shard; continue
        W = w.to(dev, torch.float32); o, i = W.shape; po, pi = -o % B, -i % B
        Wp = torch.nn.functional.pad(W, (0, pi, 0, po)).view((o + po) // B, B, (i + pi) // B, B)
        s = (Wp.abs().amax(dim=(1, 3), keepdim=True) / FMAX).clamp(min=1e-12)
        q = (Wp / s).clamp(-FMAX, FMAX).to(torch.float8_e4m3fn)
        deq = (q.to(torch.float32) * s).view(o + po, i + pi)[:o, :i]
        maxrel = max(maxrel, ((deq - W).norm() / W.norm()).item())
        out[k] = q.view(o + po, i + pi)[:o, :i].contiguous().cpu()
        out[k[:-len("weight")] + "weight_scale_inv"] = s.view(s.shape[0], s.shape[2]).contiguous().cpu()
        wm[k] = wm[k[:-len("weight")] + "weight_scale_inv"] = shard; nq += 1
    save_file(out, str(dst / shard), metadata={"format": "pt"}); print("shard", shard, flush=True)
for f in src.iterdir():
    if f.is_file() and not f.name.endswith(".safetensors") and f.name not in ("model.safetensors.index.json", "config.json"):
        shutil.copy2(f, dst / f.name)
cfg = json.loads((src / "config.json").read_text())
cfg["quantization_config"] = {"quant_method": "fp8", "fmt": "e4m3", "activation_scheme": "dynamic", "weight_block_size": [B, B]}
(dst / "config.json").write_text(json.dumps(cfg, indent=2))
(dst / "model.safetensors.index.json").write_text(json.dumps({"metadata": {}, "weight_map": wm}, indent=2))
print(json.dumps({"quantized_tensors": nq, "max_rel_frobenius_err": round(maxrel, 5)}))
