# vLLM 0.19.1 + Qwen3.8-27B-FP8 — full B2 on valid46 (one repetition)

| | llama.cpp Q8_0 (historical) | vLLM FP8, eager, 8×8 |
|---|---|---|
| TP/FP/FN/TN | 15/0/8/23 | 15/1/8/22 |
| F1 | 0.7895 | 0.7692 |
| Whole wall | 1743.8 s | 1417.5 s (startup ≈198 s) |
| Calls | 179 | 171 (0 technical, 0 default-zero) |
| Tokens in/out | 686653 / 118421 | 664515 / 107958 |

Changed together: engine + quantization → not a matched control. The one flip is
`airline__10::t19` (TN→FP).

Setup fixes on the way (commits on `perf/qwen-inference-20261010`):
- hash-locked wheelhouse (185 wheels, all SHA256 verified), offline `--require-hashes` install;
- verifier: LFS-tracked `tokenizer.json` must be checked by LFS SHA256, not pointer blobId;
- vLLM 0.19.1 removed `--disable-log-requests`.

Gate deviation: smoke failed only on its 600 s budget (startup inside budget, workers=1);
full46 launched directly (`full_direct.sh` in receipts).

Headroom: GPU ~38 % / ~130 W. Next engine-only step: drop `--enforce-eager`, raise workers/slots.
Receipts: `outputs/qwen_inference_20261010/vllm_b2_fp8_full46_c11f4aca.zip`, summary JSON alongside.
