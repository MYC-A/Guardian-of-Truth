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

## Explicit numeric-control amendment before collecting gradient magnitudes

The first full-model trial rejected strict bit-exact admission on both fixed
TRAIN inputs: 48.715/34.931 seconds and 46.113/29.935 seconds (reference/compiled).
The candidate was not used for optimizer updates; the resumed trainer fell back
to original dequantization, then stopped gracefully, still at step 29/464 rows.
The initial receipt has only equality booleans, not gradient error magnitudes.

Before the diagnostic restart, the following replacement admission rule is fixed:
warm both weight shapes, require exact dequant weights under BF16 autocast, and
run original/original-repeat/compiled with the same saved dropout RNG for each of
the same two TRAIN inputs. Require all gradients finite, equal post-dropout RNG,
score and loss differences <=1e-5, gradient global relative L2 <=0.005 and no more
than twice original-repeat error plus 1e-7, worst tensor relative L2 <=0.02, and
maximum gradient absolute difference <= twice original-repeat difference +1e-7.
Require >=10 percent speedup including standalone compiler warmup. These numeric
bounds are fixed before collecting the diagnostic gradient magnitudes and never
use validation quality. This explicitly replaces strict full-gradient bit equality;
strict equality remains separately reported. Acceptance is exploratory and does
not assert absolute equivalence or improved validation/private quality.

Both stopped optimizer checkpoints are backed up off-box. The discarded partial
batch consumed dropout RNG; continuation restores the actually saved RNG state.
It is not claimed to reproduce an uninterrupted trajectory bit for bit.

## Measured admission and user-approved complete pass

Both full-model controls passed the declared numeric-noise criterion. The first
original/original repeat gradient relative L2 was 0.00045461; compiled/reference
was 0.00043291. The second was 0.00096957 versus 0.00098463. All score/loss deltas
were zero and post-dropout RNG matched. Full gradients were not bit exact.
Warm projection dequantization was exact on both executed weight shapes.

Steady second-input time: 45.8596 seconds reference versus 30.0702 seconds compiled
(1.525x). The first reference took 150.5843 seconds on a cold model and is not
used to claim a larger steady speedup. Optimized dequantization is enabled in
resume-v2; no quality improvement has yet been measured.

The user explicitly approved completing one full pass after the 8-9 hour remaining
training estimate plus 1-2 hours evaluation. The active segment is not interrupted.
A finite supervised followup waits for resume-v2, then continues its final saved
adapter/Adam/order/RNG to 1458 total rows. It never starts a second epoch.
Total optimizer wall time safety cap becomes 57600 seconds (16 hours INCLUDING
all previous segments), not 16 additional hours. Technical setup/probes remain
separate. This is a resource-budget amendment, not tuning on heldout results.

The waiting followup deadline is 4 hours, its training monitor deadline is 8 hours,
and its supervisor wrapper deadline is 12 hours. Final evaluation waits up to
12 hours for a full-epoch receipt and has a 15-hour overall wrapper bound. The
off-box collector has a finite 16-hour lifetime. Partial training is explicitly
rejected by --require-full-epoch before evaluation; all diagnostics/checkpoints
are still archived on failure. These are safety ceilings, not duration forecasts.
