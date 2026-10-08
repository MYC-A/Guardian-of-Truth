# Independent runtime review — 2026-10-08

Read-only review of Qwen B2 while the frozen 8-slot baseline and queued 16-slot comparison were running. No running stage was edited, no model requests were issued, and no packages were installed. These are implementation findings and partial-run diagnostics, not a completed speed or quality comparison.

## Observed cost

Evidence: `/workspace/guardian/submission/bench-baseline-20261008/traces.jsonl` and `llama-server.log`.

- At 04:59:30 UTC, baseline PID 8223/model PID 8257 had elapsed 735 seconds and 17/46 rows were complete. The informal estimate of 25 minutes for that snapshot was incorrect.
- Deduplicated steps in those completed rows contained 21,613 pre_blind output tokens, 10,419 review tokens and 2,784 F-extraction tokens. Pre-analysis is a substantial generation cost; changing its schema or token budget changes the method and requires a quality comparison.
- The log then contained 72 completed tasks: summed prompt-processing time 367.703 seconds and generation time 4,973.464 seconds. These overlapping per-task times are **not GPU wall time**. Typical long replies decoded at approximately 9–10 tokens/s per active slot. No prompt truncation was observed in that snapshot.
- The bundled llama-server help reports FlashAttention `auto`, continuous batching enabled and prompt caching enabled by default. The historical model alias ends in `llamacpp-b11459`; the actual bundled engine is build `f498f864fbc0472004ee1c3616c1188c68eb157f`. Re-enabling defaults is not itself a new optimization. Compare the queued 16-slot profile against the complete baseline using identical weights, inputs, budgets and output scoring.
- The `/v1/chat/completions/input_tokens` implementation in `tools/server/server-context.cpp::handle_count_tokens` applies the chat template and tokenizes; it does not schedule GPU generation. Its CPU overhead was not independently timed.

## F pre-eligibility opportunity — not enabled

`src/guardian_truth/v6fix/turnrules.py::bind` adds an unresolved applicability condition whenever `_unparsed_context_sources(normative_sources)` is nonempty. Under this contract, no returned extraction can become MECHANICAL for that input, but `F.extract` still makes two calls.

At a later snapshot of 28 completed rows, 17 distinct F policy keys produced 28 HYPOTHESIS and 3 DROPPED rules, with zero MECHANICAL rules. For 14 keys, every returned rule explicitly recorded nonempty `unparsed_context_source_ids`.

A future optimization can skip extraction when the same code-owned precondition establishes that mechanical binding is impossible. It must record `SKIPPED_UNSUPPORTED_BINDING`, preserve eligible inputs, and acknowledge the loss of diagnostic hypotheses. Do not infer eligibility from IDs, tool names or domains. Keep this disabled until proof-contract contrast tests and a paired full replay establish unchanged final decisions. The partial snapshot does not establish the total speed benefit.

## Thread safety

- No DF4/executor global monkeypatch was found in the reviewed path.
- `repair/v5.py::cb_run` temporarily replaces `confirm.binding` and `confirm.compare`; concurrent calls can race during capture/restore. **This path is inactive in B2**, which uses `with_cb=False`. Fix with local dependency injection or appropriate serialization before enabling it concurrently.
- Shared `Layers.cache` permits concurrent misses, but `LocalClient` singleflight deduplicates identical request/attempt pairs. `F.bind` builds new dictionaries rather than mutating cached extraction rules. No semantic cross-row contamination was demonstrated on this path.

## Existing vLLM is not a drop-in GGUF control

Read from installed package metadata/source in `/workspace/guardian/serve_venv`: Python 3.12.3, vLLM 0.31.0, PyTorch 2.13.0, Transformers 5.17.0 and Triton 3.7.1. The installed vLLM has no GGUF loader or GGUF quantization registration; its package tree contains no GGUF implementation. The `gguf` Python package is absent.

The existing weight file's GGUF header declares `general.architecture=qwen35`, name `Qwen3.8-27B`, 64 blocks and full-attention interval 4: 48 recurrent/SSM blocks and 16 full-attention blocks. Qwen3.5 classes exist in vLLM's registry, so the marketing name alone is not an architecture blocker. The actual obstacle to a direct same-file control is the missing GGUF loader/quantization path. Conversion or a different runtime version is a separate experiment, not a proven speed improvement.

## Failure classification and validation limits

- Confirmed the optional pre-injection byte-budget fallback bug: a successful unchanged primary review could be mislabeled as `PRIMARY_INFERENCE_FAILURE` because the legacy helper inspected optional `pre_steps`. The repaired terminal projection checks the primary record separately and retains optional gaps. Valid negative, valid positive and actual primary failure contrasts passed.
- Reviewed the initial offline projection: gold was read after projection, complete IDs were enforced and old traces were preserved. ID equality alone does not authenticate prompt/response bytes; the parent is adding frozen-input fingerprint checks in a separate change.
- Review validation at that snapshot: `test_submission_reproject.py`, `test_qwen_submission.py` and `test_submission_wire.py`: **19 passed, 2 POSIX tests skipped on Windows**.
- Actual isolated Linux SIGTERM/SIGINT ownership smoke: **2 passed**, owned detached child disappeared and unrelated child survived. Evidence: `/tmp/guardian_submission_signal_review_20261008_0516/{signal_results.log,signal_results.xml,cli.py,test_submission_wire.py}`. This test does **not** establish shutdown behavior with a blocked GPU HTTP worker or active ThreadPool inference.

No default runtime optimization is accepted by this review. Complete the frozen baseline/16-slot comparison before selecting a deployment profile.
