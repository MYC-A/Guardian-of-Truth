# MoE model bench on valid46 (B2 legacy pipeline unchanged), A100 80GB, vLLM 0.19.1

| Model | Slots | Compact JSON | F1 | TP/FP/FN | P | R | rows/min | startup s | DEFAULT_ZERO |
|---|---|---|---|---|---|---|---|---|---|
| Qwen3.8-27B (reference) | 16 | no | 0.821 | 16/0/7 | 1.00 | 0.70 | 5.37 | ~210 (warm) | 0 |
| Qwen3.8-27B | 64 | yes | 0.789 | 15/0/8 | 1.00 | 0.65 | 6.21 | 300 | 0 |
| Qwen3.5-35B-A3B-FP8 (baseline model) | 64 | yes | 0.619 | 13/6/10 | 0.68 | 0.57 | 16.8 | 304 | 0 |
| Qwen3.6-35B-A3B | 16 | no | 0.541 | 10/4/13 | 0.71 | 0.43 | 13.5 | 294 | 3 |
| Gemma-4-26B-A4B-it-FP8-dynamic | 16 | no | 0.357 | 5/0/18 | 1.00 | 0.22 | 9.6 | 178 | 11 |
| Gemma-4-26B-A4B-it-FP8-dynamic | 64 | yes | 0.545 | 9/1/14 | 0.90 | 0.39 | 18.1 | 192 | 0 |
| GLM-4.7-Flash-FP8-Dynamic | 64 | yes | n/a (0.083) | 1/0/22 | - | - | - | - | 45 (Marlin FP8 kernel error on A100: unsupported `a` scalar_type) |
| GLM-4.7-Flash-FP8-Dynamic (workaround: --no-enable-prefix-caching --no-enable-chunked-prefill --max-num-batched-tokens 32768) | 64 | yes | 0.143 | 2/3/21 | 0.40 | 0.09 | 10.2 | 171 | 3 |

Compact JSON = `--structured-outputs-config '{"backend":"xgrammar","disable_any_whitespace":true}'`.
OR-ensembles with Qwen3.8 give no gain (q38|g4 = 0.821, q38|q36 = 0.744).
GLM error cause (vLLM 0.19.1 bug): on A100 Marlin repacks FP8 kv_b_proj weights to int32; MLA `_compute_prefill_context` (used for prefix-cache hits / chunked context) casts input to the weight dtype -> int32 -> marlin_gemm rejects it. Avoided by disabling prefix caching and chunked prefill. With the workaround outputs are valid JSON (376 stop / 10 length), so the low F1 is model quality, not a failure.

Conclusion: no tested MoE model approaches Qwen3.8-27B quality; keep Qwen3.8 and speed it up instead.
