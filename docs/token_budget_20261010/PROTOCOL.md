# Request budget in native tokens instead of the 60 000-byte cap — protocol

Committed BEFORE the GPU run.

## Problem
`predict_one` caps every request at 60 000 serialized UTF-8 bytes (≈ 8.5k tokens) although the served
context is 32 768 tokens. Over the cap the hook silently drops add-ons (blind pre-analysis, checklist) and
sends the bare B2 review. In the B2 graph16 valid46 run 14/46 rows lost the pre-analysis this way
(requests 60 048–77 957 bytes). The cap is historical (API era); a 60→80 KB test earlier gave +1 TP/+1 FP.

## Change (opt-in, `--token-budget` in the vLLM adapter)
- `Hook(token_budget=...)`: a request fits iff native input tokens (same `/tokenize` preflight the client
  uses before every call) + reserved `max_tokens` ≤ served context. Same rule for the send check and the
  add-on fallback (`Hook.call`, checklist hook). If counting fails, that request falls back to the old byte cap.
- `VllmClient.count_tokens` (cached by exact preflight; validates count and served context);
  `budget_preflight_http` reported in DONE.json.
- Default (no flag / `token_budget=None`): requests, receipts and adapter calls are byte-identical (tested).
- Content budgets (packer 20 000 bytes, blind view 20 000 bytes) are NOT changed here (next step).

## Checks before GPU
New tests: `tests/test_token_budget.py` (6), adapter `count_tokens`/flag (2). Full suite: 3713 passed;
the 28 failed + 4 collection errors are identical to the pre-change commit b3eb1f1d (stale artefacts).
Code review of the diff; two bugs found by tests and fixed before commit (class placement, test fixtures).

## Short GPU test (technical + early signal, not a decision)
valid46, graph16 config, `--token-budget` only (no checklist). Compare with B2 graph16 (TP16 FP0 FN7, F1 .8205).
Gates: 0 technical calls; no NOT_EXECUTED_CONTEXT_BUDGET; pre-analysis delivered on all rows where it was
produced; wall ≤ 1800 s. Report: delivered count, label changes (expected only among the 14 rows plus noise),
max input tokens. valid46 is contaminated/small (noise ±0.05 F1): no adoption decision from this alone.
