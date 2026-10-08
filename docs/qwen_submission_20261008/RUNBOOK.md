# Offline Qwen B2 submission

This archive runs the measured B2 pipeline using its bundled Qwen Q8_0 GGUF,
llama.cpp, CPython3.12 and native Python dependencies. No external API, weights
download, research predictions, gold or input-ID lookup is used.

Platform interface:

```sh
pip install .
python scripts/predict.py --input /data/test.parquet --output /data/predictions.parquet
```

CSV and Parquet inputs are detected by content. Output defaults to Parquet even
when the supplied filename ends .csv; use --output-format csv for a local CSV
consumer. Output preserves exact string IDs and input order. Only id,prompt,
response are retained from the input. Existing output paths are rejected.

Requires Linux x86_64, CUDA12-compatible NVIDIA driver and one A10080GB. The
host supplies libcuda; userspace CUDA libraries are included. The staged native
runtime is built on Ubuntu24.04; validate against the target runner before
assuming compatibility with older GLIBC hosts.

Default: eight parallel rows/slots,32768 context tokens per slot, reasoning off.
The same byte-bounded evidence views as B2 are retained; their unread gaps remain
in traces. Exact server tokenizer + reserved output preflight forbids silent
context truncation. Primary technical failure aborts with receipts, never a
fabricated negative. Internal UNKNOWN follows the historical binary0 projection;
it is not certified absence of a violation.

Diagnostics: --work-dir /writable/path keeps traces.jsonl, calls.json, run.json,
llama-server.log. --attach --port8081 connects only to an already-running local
server with the exact model alias and slot context. Submission defaults start
and stop only their own model process. --fast is a separate experimental profile
enabling FlashAttention; do not claim unchanged quality before a paired test.

Local Docker verification (from unpacked archive root):

```sh
docker build -t guardian-qwen:b2 .
docker run --rm --gpus all --network none --user "$(id -u):$(id -g)" \
  -v /absolute/data:/data guardian-qwen:b2 \
  --input /data/test.parquet --output /data/predictions.parquet
```

Upload the ZIP, not this Docker registry name: Guardian's documented interface
unpacks source files. The archive must have scripts/predict.py and pyproject.toml
directly at root, no wrapper folder or metrics directory. Verify uploaded file
size strictly below40GB and compare the published SHA256 after download.
The package is a candidate until a complete cold full-run timing/quality check
has passed. No competition submission is made automatically.

Research-only replay after a complete benchmark (not included in the archive):

```sh
python scripts/qwen_submission_reproject.py --input valid.parquet \
  --traces /path/to/frozen/traces.jsonl --output-dir /path/to/NEW/projection
```

It blocks network access, requires exactly the full input ID set, shares the
live final projection, preserves raw files and reports the wrapper correction
separately. Labels are read only after projection for scoring; they never enter
the runtime. A real primary failure prevents a full prediction file and produces
explicit full-denominator sensitivity bounds rather than an imputed negative.
