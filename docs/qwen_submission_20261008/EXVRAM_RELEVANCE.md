# ExVRAM article: applicability to Guardian, 2026-10-08

Primary sources reviewed:

- https://habr.com/ru/articles/1091550/
- https://github.com/ExVRAM/exvram-lab

The authors report 30.10 decode tokens/s over five runs on an RTX5060 8GB,
using UD-IQ2_XXS weights, q4_0 KV and a genuinely occupied8192-token prompt.
Their quality gate is unfinished. Their target is interactive batch1 inference.
This is not a matched comparison with Guardian Q8_0, F16 KV, multiple slots and
multi-stage JSON generation. Their measurements have not been independently
reproduced here.

Useful checks: verify actual GPU layer placement; record occupied context rather
than allocated capacity; distinguish prefill, decode and whole-input elapsed
time; evaluate weight/KV quantization against task quality.

Guardian actions:

1. Complete the already running whole-valid46 control and queued workers16,
   FlashAttention, batch8192 arm, retaining Q8 weights and existing prompts.
2. Report complete IDs, technical failures, binary metrics and wall timing.
3. Treat KV quantization as a subsequent separate arm if memory/throughput
   measurements justify it. Do not replace Q8 with IQ2 on a speed claim alone.

No ExVRAM code, weights or launcher has been imported into the submission.
