# Qwen3.8 B2 graphs16: input identity repair

This standalone candidate preserves Qwen/Qwen3.8-27B-FP8 revision
017b9c7af6b5689d5dd426a76e0bc077eb5ca20a and the original B2 pipeline.
The source is the previously verified toolchain-fixed archive, SHA256
bcdb2a884f2a369b53eeee468a1f16b24202b0ef6524e551452e7a27ec116382.

Preserved inference settings: vLLM 0.19.1, 16 workers and 16 sequences, context
32768, GPU memory utilization 0.88, prefix caching, chunked prefill, BF16 compute,
KV cache dtype auto, CUDA graphs permitted, thinking disabled. All model files,
runtime dependencies, toolchain fixes, B2 prompts, admission, retries and fallback
logic are copied unchanged. The adapter adds only bounded row progress logging.

Input accepts CSV and Parquet (identified by PAR1 magic). CSV permits fields above
128 KiB, quoted multiline text, BOM and additional columns. Duplicate normalized
column names are rejected. Only id, prompt and response enter the clean snapshot.
Prompt and response must be strings. CSV ids remain verbatim, including empty,
numeric-looking and duplicate values; scalar Parquet ids are converted to text.

Each input row receives an internal position key before B2. Outputs are checked
against those unique keys before original ids are restored in the original order.
The requested .parquet/.pq suffix produces real Parquet; other paths produce CSV
with columns id,label. Existing output files cannot be overwritten.

```bash
pip install .
python scripts/predict.py --input /data/test.csv --output /data/predictions.csv
```

No network or model download is needed during inference. Model-start failure
leaves no output. Existing B2 per-row DEFAULT_ZERO recovery remains in place and
is counted in progress logs; this repair does not change its quality behavior.

The original adapter duration remains 1800 seconds, including its own model
startup. This is not a guarantee of fitting the platform's whole-job limit:
installation and the outer entrypoint add overhead. No partial zero-filled file
is published merely because time runs out. A100 quality and full-test completion
must be measured separately; CPU tests and ZIP integrity do not establish them.

The builder verifies the source archive SHA256, preserves all nonpatched members,
checks every final member's SHA256, CRC and Unix mode, enforces a strict
40,000,000,000-byte cap and publishes a final .verification.json and .zip.sha256.
