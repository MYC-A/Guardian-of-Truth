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

## Result (code c1ae1aad, valid46, graph16 config, `--token-budget`)
Technical gates all passed: 0 technical calls, 0 NOT_EXECUTED, 0 add-on drops, token-count errors 0,
wall 690 s (incl. startup); 126 extra /tokenize preflights (cheap). Pre-analysis delivered on 45/46 rows
(graph16 B2: 31/46; the one remaining row had no parsable pre-analysis, not a budget drop).
Largest pre-step input 4.6k tokens; review requests far below 32k context.
Labels vs B2 graph16: TP14 FP1 FN9 TN22, F1 .7368 (B2 graph16 .8205). 5 rows changed:
- among the 14 former cap rows: retail__29::t13 FN→TP (the only change; 13 unchanged);
- among rows whose delivery did NOT change: banking_005 TP→FN, retail_48 TP→FN, telecom mms t10 TP→FN,
  banking_057 TN→FP — pure resampling noise (pre-analysis resampled; T=0 under batching is non-deterministic).
banking_005 and retail_48 also flipped in the checklist run → unstable rows.
Conclusion: the fix works as intended (delivery 31→45, no failures, no time cost); its own effect on the
cap rows is +1 TP / 0 FP. A single valid46 run cannot measure quality: noise here is up to ~0.08 F1.
Not a decision; quality comparisons need repeated runs and/or the larger decision pools.
