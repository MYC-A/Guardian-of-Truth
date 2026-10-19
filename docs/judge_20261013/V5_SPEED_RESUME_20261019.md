# V5: technical speed amendment, 19 October 2026

The user requested an immediate investigation and correction of low GPU use.
The running AWQ_TORCH process was observed at about one CPU core and GPU use
25 percent with excursions to 80 percent. This does not identify every bottleneck.
The installed AWQ_TORCH forward calls unpack/reorder/scale dequantization for every
expert invocation. The current training has not been edited in memory.

A separate bounded microbenchmark on actual checkpoint tensors tested compiling
the existing dequantize_gemm function with torch.compile(fullgraph=True,
dynamic=False). Six projection examples produced bit-identical BF16 weights,
outputs, and input gradients; measured dequantization speedups were 4.8 to 6.0.
These measurements share the GPU with training and are not an end-to-end speedup.
Two of the six examples came from the unused MTP tower; the other examples are
language tower experts. Full-model admission below tests the executed language path.

Before any training uses this optimization:

1. Stop only the waiting V5 post-training service, preventing premature evaluation.
2. Ask the current trainer to terminate gracefully. It discards only an uncommitted
   partial batch and saves the final committed adapter, optimizer, order, and RNG.
3. Verify/checksum and export this checkpoint off-box before resuming.
4. Resume in a separate output directory; verify original gate, model, input token
   hashes, recipe, optimizer steps, and shuffle order. Never reset optimizer or LR.
5. On the next two fixed TRAIN inputs compare original and compiled full-model
   forward/backward with the same saved dropout RNG. Require bit-identical scores,
   losses, and every adapter gradient, and at least 10 percent lower combined time
   including compiler warmup. No validation labels or performance select the path.
6. If the numerical/speed criterion fails, use the original dequantization function.
   Restore checkpoint RNG again before the first resumed optimizer update.
7. Retain the original total 32400-second optimizer budget, subtracting the original
   run's recorded training_seconds. Diagnostics/setup are reported separately.
8. Keep hourly health, finite supervisors, paired evaluation and off-box collection.

This is an explicitly recorded technical amendment during training. Dataset,
sequence order, input tokens, objective, adapter targets, optimizer, LR, batch size,
and quality evaluation protocol remain the frozen recipe. The original run and
checkpoint remain available. It is not a new independently trained replicate,
not proof that an epoch completes in nine hours, and not proof of improved F1.
