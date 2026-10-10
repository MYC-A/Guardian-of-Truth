# Assembled candidate — 2026-10-10

Final ZIP: `A:/Guardian-submissions/guardian-qwen-vllm-fp8-graphs16.zip`.

- Bytes: **36,576,333,116** (36.58 GB / 34.06 GiB).
- Strict cap: 40,000,000,000 bytes; remaining: **3,423,666,884 bytes**.
- SHA256: `ce6fc68434d81375ec81f33139c70f5e14954e880fc8ba32bd22421b4876e336`.
- 52,672 files; all 78 pinned model assets supplied, no GGUF substitution.
- Assembly and full per-member verification completed in 1316.9 seconds.
- Every file passed final SHA256/ZIP CRC, exact inventory and Unix mode checks.
- 178 tests passed; independent source/configuration and boundary reviews completed.
- Relocated Linux main/child Python, offline installation, and public empty
  Parquet execution passed. Source server stage remained unchanged.

Runtime and all prediction code come from server source
`65bf34384929a6001132d8dd6e6a8be51298d990`. Changes after that source affect
operator packaging/CI/download tools and reports, not B2 prediction modules.
The original server runtime SHA matches the downloaded transport exactly.

Profile: official FP8 revision `017b9c7af6b5689d5dd426a76e0bc077eb5ca20a`,
vLLM0.19.1 graphs16, workers16/slots16/context32768, prefix caching,
chunked prefill, thinking off. Correct strict decisions are preserved;
complete primary model decisions can recover classification; unresolved
missing labels use explicit DEFAULT_ZERO. No benchmark labels/ID lookup
are included and no prediction caches are shipped.

**Status is assembled candidate, not cold GPU validated deployment.**
The selected model and full B2 pipeline **have already completed real A100
GPU inference**: graph16 valid46 finished all 46 rows, 16TP/0FP/7FN,
F1 .820513, whole wall 677.5s, 174 completion calls, zero technical calls
and zero default-zero fallbacks. Configuration-specific torch.compile cache
was cold; approximately 162s startup, including 50.7s compile, was counted.
The saved baseline eager8 also completed valid46 (15TP/1FP/8FN,
F1 .769231, 1417.5s). These results are preserved in
`outputs/qwen_inference_20261010/vllm_b2_fp8_graph16_full46_summary.json`
and `vllm_b2_fp8_full46_summary.json` with original raw receipt ZIPs.

The remaining GPU check concerns the new portable runtime/entrypoint after
extraction, not whether Qwen/vLLM/B2 has ever run on GPU. The code/adapter
identity comparison against the successful graph16 run is documented in
`FINAL_BUILD_REVIEW.md`.

The user's separate GPU experiment remains running. This final ZIP was not
uploaded to that server. Linux checks used its equivalent existing frozen
stage, not extraction of this ZIP. Nonempty public inference, cold JIT/startup
and full/private-cohort time remain unmeasured for the packaged artifact.
Historical graph16 valid46 metrics are documented separately and are not
claimed as a new package experiment.

Receipts: `receipts/FINAL_ASSEMBLY_VERIFICATION.json`,
`receipts/ASSEMBLY_STATUS.json`, `receipts/linux_cpu/`.
Independent findings and timing differences: `FINAL_BUILD_REVIEW.md`.
Operator upload instructions: `A:/Guardian-submissions/UPLOAD_VLLM_FP8.md`.
The old Q8 archive is preserved.
